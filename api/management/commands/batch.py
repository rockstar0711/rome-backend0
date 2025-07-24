import os
import re
import uuid
import subprocess
from django.core.management.base import BaseCommand
from django.conf import settings
from api.models import SessionModel, SummaryModel, UserModel
from django.core.files.storage import default_storage

import boto3
from deepgram import DeepgramClient, PrerecordedOptions
from openai import OpenAI

from imageio_ffmpeg import get_ffmpeg_exe


class Command(BaseCommand):
    help = "Process sessions missing audio/transcripts/sentences"

    def handle(self, *args, **kwargs):
        sessions = SessionModel.objects.filter(video_url__isnull=False)
        
        default_user = UserModel.objects.first()
        if not default_user:
            print("❌ No users found in the system. Cannot assign summaries.")
            return

        for session in sessions:
            if session.audio_url and session.transcript and session.sentences:
                continue  # Skip already processed

            print(f"Processing session {session.id}")

            try:
                # Download video
                video_url = session.video_url
                video_filename = f"{uuid.uuid4()}.mp4"
                video_path = os.path.join(settings.MEDIA_ROOT, f"temp/{video_filename}")

                os.makedirs(os.path.dirname(video_path), exist_ok=True)
                os.system(f"curl -s {video_url} -o {video_path}")

                # Extract audio
                audio_path = os.path.splitext(video_path)[0] + ".mp3"
                ffmpeg_path = get_ffmpeg_exe()

                command = [
                    ffmpeg_path,
                    "-i", video_path,
                    "-vn",
                    "-acodec", "libmp3lame",
                    audio_path
                ]

                subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # Upload audio to S3
                s3 = boto3.client(
                    's3',
                    aws_access_key_id=os.environ.get("ACCESS_KEY"),
                    aws_secret_access_key=os.environ.get("SECRET_ACCESS_KEY"),
                    region_name=os.environ.get("AWS_REGION"))
                bucket_name = os.environ.get("AWS_S3_BUCKET_NAME")

                unique_id = str(uuid.uuid4())
                s3_audio_key = f"{session.id}_{unique_id}.mp3"

                s3.upload_file(audio_path, bucket_name, s3_audio_key)

                audio_url = f"https://{bucket_name}.s3.amazonaws.com/{s3_audio_key}"
                session.audio_url = audio_url

                # Transcribe audio
                dg_client = DeepgramClient(os.environ["DEEPGRAM_API_KEY"])
                options = PrerecordedOptions(
                    model="nova-3",
                    language="en",
                    smart_format=True,
                )

                source = {"url": audio_url}
                response = dg_client.listen.prerecorded.v("1").transcribe_url(source, options)

                all_sentences = []
                paragraphs = response['results']['channels'][0]['alternatives'][0]['paragraphs']['paragraphs']
                index = 0
                for para in paragraphs:
                    for sentence in para['sentences']:
                        all_sentences.append({
                            "id": index,
                            "text": sentence['text'],
                            "start": sentence['start'],
                            "end": sentence['end']
                        })
                        index += 1
                transcript = response['results']['channels'][0]['alternatives'][0]['transcript']

                session.transcript = transcript
                session.sentences = all_sentences

                summary = self.summarize_transcript(transcript)

                SummaryModel.objects.update_or_create(
                    session=session,
                    defaults={
                        "user": default_user,
                        "content": summary
                    }
                )

                session.save()

                os.remove(video_path)
                os.remove(audio_path)

                print(f"Successfully processed session {session.id}")

            except Exception as e:
                print(f"Failed to process session {session.id}: {e}")

    def split_transcript(self, transcript, max_chars=8000):
        sentences = transcript.split('. ')
        chunks = []
        current = ''
        for sentence in sentences:
            sentence += '. '
            if len(current) + len(sentence) <= max_chars:
                current += sentence
            else:
                chunks.append(current.strip())
                current = sentence
        if current:
            chunks.append(current.strip())
        return chunks

    def summarize_transcript(self, transcript):
        client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
        prompt_template = """
            You are an assistant that outputs only HTML. Use <h2> or <h3> for headings, <p> for paragraphs, <strong> for bold, <em> for italic, and <ul><li> for bullet lists. Do not include any extra text or code blocks. 

            Here's the content to format:
            - Title: Project Overview
            - Sections:
            1. Goals: Describe the goals in 2-3 sentences.
            2. Features: List key features as bullet points: user auth, data export, notifications or anything else.
            3. Notes: Emphasize any special considerations in bold or italic.

            Generate the HTML for this content.
            
            Here's the transcript to format into HTML:
            {chunk}
        """.strip()

        try:
            chunks = self.split_transcript(transcript)
            summaries = []

            for i, chunk in enumerate(chunks):
                print(f"🧠 Summarizing chunk {i + 1}/{len(chunks)}...")
                prompt = prompt_template.format(chunk=chunk)

                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}]
                )
                summaries.append(response.choices[0].message.content)

            return "\n\n".join(summaries)

        except Exception as e:
            raise RuntimeError(f"OpenAI summarization failed: {e}")