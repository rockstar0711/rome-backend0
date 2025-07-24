import os
import math
import boto3
import uuid
import json
from openai import OpenAI
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from django.conf import settings
from django.shortcuts import render
from django.core.files.storage import default_storage
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ViewSet
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .serializers import *
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework.response import Response
from rest_framework import viewsets
from rest_framework import generics
from rest_framework.decorators import action
from rest_framework.generics import GenericAPIView, RetrieveAPIView
from django.shortcuts import get_object_or_404
import json
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils.timezone import now
from django.utils.crypto import get_random_string
from datetime import timedelta
from django.contrib.auth.hashers import check_password, make_password
from api.utils import send_email
from django.core.management import call_command
from django.contrib.auth.models import User
from django.db.models import Prefetch, Avg, Max, Count, Sum, F, Q
from collections import defaultdict
from django.http import Http404
from .permissions import IsStaffOrReviewer, IsStaffOrSuperAdmin, IsStaffOrReviewerOrReadOnly
from django.db.models.functions import Lower, TruncMinute
import resend
from django.template.loader import render_to_string
from api.management.commands.sync_zenus_data import sync_project_list, sync_single_project
from imageio_ffmpeg import get_ffmpeg_exe
import subprocess
import re
from boto3.s3.transfer import TransferConfig
from tqdm import tqdm  # Optional for testing locally
from deepgram import DeepgramClient, PrerecordedOptions, FileSource
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

resend.api_key = os.environ.get("RESEND_API_KEY")
support_email = os.environ.get("NNG_EMAIL")

# Create your views here.

class LoginViewSet(ModelViewSet, TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = (AllowAny,)
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        user_data = serializer.validated_data.get("user")

        if not user_data.get("email_verified"):
            # Handle unverified email logic
            VerificationTokenModel.objects.filter(email=user_data["email"]).delete()

            verification_token = get_random_string(length=32)
            expiration_time = now() + timedelta(hours=1)

            VerificationTokenModel.objects.create(
                email=user_data["email"],
                token=verification_token,
                expires=expiration_time,
            )

            frontend_url = os.environ.get("FRONTEND_URL")
            self.send_verification_email(user_data["email"], verification_token, frontend_url)

            return Response(
                {"message": "Email not verified. A new verification email has been sent."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(serializer.validated_data, status=status.HTTP_200_OK)

    def send_verification_email(self, email, token, frontend_url):
        # Build verification link
        verification_link = f"{frontend_url}/verify-email?token={token}"

        context = {
            "verification_link": verification_link,
        }
        
        send_email(
            # we current in testing email so we need to uncommend this in the future
            to=email,
            subject="Verify Your Email",
            template_name="verification_email.html",
            context=context,
        )



class RegisterationViewSet(ModelViewSet, TokenObtainPairView):
    serializer_class = RegisterSerializer
    permission_classes = (AllowAny,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Save the new user
        user = serializer.save()

        # Remove existing token for the email if it exists
        VerificationTokenModel.objects.filter(email=user.email).delete()

        # Generate a verification token
        verification_token = get_random_string(length=32)
        expiration_time = now() + timedelta(hours=1)  # Token expires in 1 hour

        # Create a new row in VerificationTokenModel
        VerificationTokenModel.objects.create(
            email=user.email,
            token=verification_token,
            expires=expiration_time,
        )

        # Here, you can send the verification email (implementation depends on your email backend)
        frontend_url = os.environ.get("FRONTEND_URL")
        self.send_verification_email(user.email, verification_token, frontend_url)

        return Response(
            {"message": "User registered successfully. Email verification sent."},
            status=status.HTTP_201_CREATED,
        )
        
    def send_verification_email(self, email, token, frontend_url):
        # Build verification link
        verification_link = f"{frontend_url}/verify-email?token={token}"

        context = {
            "verification_link": verification_link,
        }
        
        send_email(
            # we current in testing email so we need to uncommend this in the future
            to=email,
            subject="Verify Your Email",
            template_name="verification_email.html",
            context=context,
        )





    # except:
    #     return Response({"status":"error", "data":""}, status=status.HTTP_400_BAD_REQUEST)


class UserLogoutView(GenericAPIView):
    permission_classes = (IsAuthenticated,)
    
    def post(self, request, *args, **kwargs):
        try:
            refresh_token = request.data["refresh"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response(status= status.HTTP_400_BAD_REQUEST)
        

class RefreshViewSet(ViewSet, TokenRefreshView):
    permission_classes = (AllowAny,)
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        return Response(serializer.validated_data, status=status.HTTP_200_OK)

class UserListViewSet(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            filters = {}

            # Check for each query parameter and add it to the filters if it's not an empty string
            if request.query_params.get("role") not in ("", None):
                filters["is_staff"] = request.query_params.get("role") == "staff"
            if request.query_params.get("status") not in ("", None):
                filters["is_active"] = request.query_params.get("status") == "active"

            # if self.request.user.is_superuser:
            userlistInstance = UserModel.objects.filter(**filters).exclude(id=request.user.id)
            userlistSerializer = UserSerializer(userlistInstance, many=True)
            return Response(
                {"status": "success", "data": userlistSerializer.data},
                status=status.HTTP_200_OK,
            )
            # else:
            #     return Response(
            #         {"status": "error", "data": "Permissoin denied"},
            #         status=status.HTTP_400_BAD_REQUEST,
            #     )
        except:
            return Response(
                {"status": "error", "data": "Server Error"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class AdminUserActionViewSet(APIView):
    permission_classes = [IsAdminUser]
    
    def post(self, request):
        # only superusers can add
        if not request.user.is_superuser:
            return Response(
                {"status": "error", "data": "permission denied"},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = UserSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"status": "error", "data": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()
        password = serializer.validated_data.get('password')
        self.send_welcome_invitation_email(user.email, user.username, password)
        return Response(
            {"status": "success", "data": serializer.data},
            status=status.HTTP_201_CREATED,
        )


    def put(self, request):
        try:
            if request.user.is_superuser == True:
                user = UserModel.objects.get(id=request.data["user_id"])
                serializer = UserSerializer(user, data=request.data, partial=True)
                if serializer.is_valid():
                    serializer.save()
                    return Response(
                        {"status": "success", "data": serializer.data},
                        status=status.HTTP_200_OK,
                    )
                else:
                    return Response(
                        {"status": "error", "data": serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response(
                    {"status": "error", "data": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except:
            return Response(
                {"status": "error", "data": ""}, status=status.HTTP_400_BAD_REQUEST
            )

    def delete(self, request):
        try:
            userInstance = get_object_or_404(UserModel, id=request.data["user_id"])
            userInstance.delete()
            return Response(
                {"status": "success", "data": "User removed successfully"},
                status=status.HTTP_200_OK,
            )
        except UserModel.DoesNotExist:
            return Response(
                {"status": "error", "data": "User does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

    def send_welcome_invitation_email(self, email, name, temp_password):
        frontend_url = os.environ.get("FRONTEND_URL")
        login_link = f"{frontend_url}/login"
        context = {
            "user_email": email,
            "user_name": name,
            "temporary_password": temp_password,
            "login_link": login_link,
        }
        send_email(
            to=email,
            subject="Welcome to ROME!",
            template_name="invitation_welcome_email.html",
            context=context,
        )

class GetPresignedUrlView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        session_id = request.data.get("session_id")
        if not session_id:
            return Response(
                {"status": "error", "message": "session_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        s3_client = boto3.client(
            's3',
            aws_access_key_id=os.environ.get("ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION")
        )
        bucket_name = os.environ.get("AWS_S3_BUCKET_NAME")
        unique_id = str(uuid.uuid4())
        key = f"{session_id}_{unique_id}.mp4"

        try:
            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': bucket_name,
                    'Key': key,
                    'ContentType': 'video/mp4'
                },
                ExpiresIn=3600  # URL expires in 1 hour
            )
            return Response(
                {"status": "success", "presignedUrl": presigned_url, "key": key},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class AdminMatchActionView(APIView):
    permission_classes = [IsAdminUser]

    def put(self, request):
        try:
            session_id = request.data.get("session_id")
            video_url = request.data.get("video_url")
            if not session_id or not video_url:
                return Response(
                    {"status": "error", "message": "session_id and video_url are required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            session = get_object_or_404(SessionModel, id=session_id)
            session.video_url = video_url
            session.save()

            return Response(
                {"status": "success", "message": "Session video_url updated successfully", "session_id": session.id},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
class AdminUploadVideoView(APIView):
    permission_classes = [IsAdminUser]

    def send_progress_update(self, stage, progress):
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "video_upload_progress",
            {
                'type': 'send_progress',
                'stage': stage,
                'progress': progress,
            }
        )

    def put(self, request):
        try:
            template_id = request.POST.get("template_id")
            session_id = request.POST.get("session_id")
            video_file = request.FILES.get("video_file")

            if not session_id or not video_file or not template_id:
                return Response(
                    {"status": "error", "message": "Missing session_id or video_file or template_id"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            session = SessionModel.objects.get(id=session_id)
            template = AITemplateModel.objects.get(id=template_id)

            self.send_progress_update('uploading_video', 0)

            # Save video locally
            temp_video_path = default_storage.save(f"temp/{video_file.name}", video_file)
            self.send_progress_update('uploading_video', 100)

            self.send_progress_update('converting_video', 0)
            # Extract audio using ffmpeg
            video_full_path = os.path.join(settings.MEDIA_ROOT, temp_video_path)
            audio_path = os.path.splitext(video_full_path)[0] + ".mp3"

            # Use imageio's ffmpeg binary
            ffmpeg_path = get_ffmpeg_exe()

            # Get video duration first
            probe = subprocess.run(
                [ffmpeg_path, "-i", video_full_path],
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                text=True
            )

            duration_match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', probe.stderr)
            if not duration_match:
                raise RuntimeError("Could not determine video duration.")
            
            h, m, s = map(float, duration_match.groups())
            total_seconds = h * 3600 + m * 60 + s

            # Command to extract audio
            command = [
                ffmpeg_path,
                "-i", video_full_path,
                "-vn",
                "-acodec", "libmp3lame",
                audio_path
            ]

            process = subprocess.Popen(
                command,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )

            while True:
                line = process.stderr.readline()
                if not line:
                    break

                # Look for time= in stderr output
                time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                if time_match:
                    ch, cm, cs = map(float, time_match.groups())
                    current_seconds = ch * 3600 + cm * 60 + cs
                    percent = int((current_seconds / total_seconds) * 100)
                    self.send_progress_update('converting_video', min(percent, 99))  # prevent early 100%

            # Wait for FFmpeg to finish
            process.wait()
            if process.returncode != 0:
                raise RuntimeError("FFmpeg failed during audio extraction.")
            
            self.send_progress_update('converting_video', 100)

            self.send_progress_update('uploading_video_to_s3', 0)

            # Upload both to S3
            s3 = boto3.client(
                's3',
                aws_access_key_id=os.environ.get("ACCESS_KEY"),
                aws_secret_access_key=os.environ.get("SECRET_ACCESS_KEY"),
                region_name=os.environ.get("AWS_REGION"))
            bucket_name = os.environ.get("AWS_S3_BUCKET_NAME")

            unique_id = str(uuid.uuid4())

            s3_video_key = f"{session_id}_{unique_id}.mp4"
            s3_audio_key = f"{session_id}_{unique_id}.mp3"

            # Helper for progress reporting
            class ProgressCallback:
                def __init__(self, total_size, label, outer_self):
                    self._seen_so_far = 0
                    self._total = total_size
                    self._label = label
                    self._outer_self = outer_self  # <--- pass outer 'self' here

                def __call__(self, bytes_amount):
                    self._seen_so_far += bytes_amount
                    percent = int((self._seen_so_far / self._total) * 100)
                    self._outer_self.send_progress_update(self._label, min(percent, 99)) 

            video_size = os.path.getsize(video_full_path)
            audio_size = os.path.getsize(audio_path)

            # Upload video with progress
            s3.upload_file(
                video_full_path,
                bucket_name,
                s3_video_key,
                Callback=ProgressCallback(video_size, 'uploading_video_to_s3', self)
            )

            self.send_progress_update('uploading_video_to_s3', 100)

            self.send_progress_update('uploading_audio_to_s3', 0)

            # Upload audio with progress
            s3.upload_file(
                audio_path,
                bucket_name,
                s3_audio_key,
                Callback=ProgressCallback(audio_size, 'uploading_audio_to_s3', self)
            )

            video_url = f"https://{bucket_name}.s3.amazonaws.com/{s3_video_key}"
            audio_url = f"https://{bucket_name}.s3.amazonaws.com/{s3_audio_key}"

            self.send_progress_update('uploading_audio_to_s3', 100)

            self.send_progress_update('transcribing', 0)
            self.send_progress_update('transcribing', 80)

            DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")

            def transcribe_audio_from_url(audio_url):

                try:
                    dg_client = DeepgramClient(DEEPGRAM_API_KEY)
                    options = PrerecordedOptions(
                        model="nova-3",
                        language="en",
                        smart_format=True,
                    )

                    source = {"url": audio_url}
                    response = dg_client.listen.prerecorded.v("1").transcribe_url(
                        source,
                        options
                    )
                    return response
                except Exception as e:
                    raise RuntimeError(f"Deepgram transcription failed: {e}")
                
            try:
                response = transcribe_audio_from_url(audio_url)
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

            except Exception as e:
                return Response(
                    {"status": "error", "message": f"Transcription failed: {e}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            self.send_progress_update('transcribing', 100)

            self.send_progress_update('Summarizing', 0)
            self.send_progress_update('Summarizing', 80)
                
            try:
                summary = self.summarize_transcript(transcript, template)

                SummaryModel.objects.update_or_create(
                    session=session,
                    defaults={
                        "user": request.user,
                        "content": summary,
                    }
                )
            except Exception as e:
                return Response(
                    {"status": "error", "message": f"Summary generation failed: {e}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            self.send_progress_update('Summarizing', 100)

            # Save URL to session
            session.video_url = video_url
            session.audio_url = audio_url 
            session.transcript = transcript
            session.sentences = all_sentences
            session.save()

            # Clean up local temp files
            try:
                os.remove(video_full_path)
                os.remove(audio_path)
            except FileNotFoundError:
                pass  # already deleted or didn't exist

            return Response({
                "status": "success",
                "message": "Uploaded to S3 and saved successfully",
                "video_url": video_url,
                "audio_url": audio_url,
                "summary": summary
            })

        except Exception as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
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

    def summarize_transcript(self, transcript, template):
        client = OpenAI(api_key=os.environ['OPENAI_API_KEY'])
        # prompt_template = """
        #     You are an assistant that outputs only HTML. Use <h2> or <h3> for headings, <p> for paragraphs, <strong> for bold, <em> for italic, and <ul><li> for bullet lists. Do not include any extra text or code blocks. 

        #     Here's the content to format:
        #     - Title: Project Overview
        #     - Sections:
        #     1. Goals: Describe the goals in 2-3 sentences.
        #     2. Features: List key features as bullet points: user auth, data export, notifications or anything else.
        #     3. Notes: Emphasize any special considerations in bold or italic.

        #     Generate the HTML for this content.
            
        #     Here's the transcript to format into HTML:
        #     {chunk}
        # """.strip()

        prompt_template = """
            {template}
            {chunk}
        """.strip()

        try:
            chunks = self.split_transcript(transcript)
            summaries = []

            for i, chunk in enumerate(chunks):
                print(f"🧠 Summarizing chunk {i + 1}/{len(chunks)}...")
                prompt = prompt_template.format(chunk=chunk, template=template)

                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}]
                )
                summaries.append(response.choices[0].message.content)

            return "\n\n".join(summaries)

        except Exception as e:
            raise RuntimeError(f"OpenAI summarization failed: {e}")

class AdminUpdateProjectView(APIView):
    permission_classes = [IsAdminUser]
    serializer_class = ProjectSerializer

    def put(self, request):
        try:
            project_id = request.data.get("project_id")
            cover_image_url = request.data.get("cover_image_url")
            client_id = request.data.get("client_id", None)
            is_active = request.data.get("is_active")
            if not project_id:
                return Response(
                    {"status": "error", "message": "project_id is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Find the project
            project = get_object_or_404(ProjectModel, id=project_id)

            # Update cover image if provided
            if cover_image_url is not None:
                project.cover_image_url = cover_image_url

            if is_active is not None:
                project.is_active = is_active

            if cover_image_url is None and (client_id is None or client_id == "null"):  # Handle null values explicitly
                project.client = None
            elif cover_image_url is None:
                project.client = get_object_or_404(ClientModel, id=client_id)
            project.save()

            return Response(
                {
                    "status": "success",
                    "message": "Project updated successfully.",
                    "project": ProjectSerializer(project).data
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VerifyEmailView(APIView):
    permission_classes = []  # Allow unauthenticated access

    def get(self, request, *args, **kwargs):
        token = request.query_params.get("token", None)
        if not token:
            return Response(
                {"message": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Look up the token in the database
            verification_token = VerificationTokenModel.objects.get(token=token)

            # Check if the token has expired
            if verification_token.expires < now():
                return Response(
                    {"message": "This verification link has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Mark the user's email as verified
            user = UserModel.objects.get(email=verification_token.email)
            user.email_verified = True
            user.save()

            # Delete the token after successful verification
            verification_token.delete()

            return Response(
                {"message": "Your email has been successfully verified."},
                status=status.HTTP_200_OK,
            )

        except VerificationTokenModel.DoesNotExist:
            return Response(
                {"message": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except UserModel.DoesNotExist:
            return Response(
                {"message": "User associated with this token does not exist."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
class ProfileViewSet(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        try:
            user = UserModel.objects.get(id=request.user.id)
            serializer = UserSerializer(user)
            return Response(
                {"status": "success", "data": serializer.data},
                status=status.HTTP_200_OK,
            )
        except:
            return Response(
                {"status": "error", "data": ""}, status=status.HTTP_400_BAD_REQUEST
            )

    def put(self, request):
        try:
            user = UserModel.objects.get(id=request.user.id)
            serializer = UserSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(
                    {"status": "success", "data": serializer.data},
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"status": "error", "data": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except:
            return Response(
                {"status": "error", "data": ""}, status=status.HTTP_400_BAD_REQUEST
            )






class ForgotPasswordView(APIView):
    permission_classes = []  # Public access allowed

    def post(self, request, *args, **kwargs):
        email = request.data.get("email")

        if not email:
            return Response(
                {"message": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Check if the user exists
            user = UserModel.objects.get(email=email)

            # Remove existing reset tokens for this email
            ResetPasswordTokenModel.objects.filter(email=email).delete()

            # Generate a new reset token
            reset_token = get_random_string(length=32)
            expiration_time = now() + timedelta(hours=1)

            # Save the token to the database
            ResetPasswordTokenModel.objects.create(
                email=email,
                token=reset_token,
                expires=expiration_time,
            )

            # Send reset password email
            frontend_url = os.environ.get("FRONTEND_URL")
            reset_link = f"{frontend_url}/reset-password?token={reset_token}"
            send_email(
                to=email,
                subject="Reset Your Password",
                template_name="reset_password_email.html",
                context={"reset_link": reset_link},
            )

            return Response(
                {"message": "Password reset email sent."},
                status=status.HTTP_200_OK,
            )
        except ObjectDoesNotExist:
            return Response(
                {"message": "No user found with this email."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"message": f"An unexpected error occurred: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class ResetPasswordView(APIView):
    permission_classes = []  # Public access allowed

    def post(self, request, *args, **kwargs):
        token = request.data.get("token")
        new_password = request.data.get("password")

        # Validate required fields
        if not token:
            return Response(
                {"message": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not new_password:
            return Response(
                {"message": "Password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Validate token
            reset_token = ResetPasswordTokenModel.objects.get(token=token)

            # Check if the token has expired
            if reset_token.expires < now():
                return Response(
                    {"message": "This reset password link has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Fetch the user associated with the token
            user = UserModel.objects.get(email=reset_token.email)

            # Validate password strength (optional)
            if len(new_password) < 8:
                return Response(
                    {"message": "Password must be at least 8 characters long."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Reset the user's password
            user.password = make_password(new_password)  # Hash the password
            user.save()

            # Delete the used token
            reset_token.delete()

            return Response(
                {"message": "Password has been successfully reset."},
                status=status.HTTP_200_OK,
            )

        except ResetPasswordTokenModel.DoesNotExist:
            return Response(
                {"message": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except UserModel.DoesNotExist:
            return Response(
                {"message": "No user associated with this token."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            return Response(
                {"message": f"An unexpected error occurred: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class UpdatePasswordView(APIView):
    permission_classes = [IsAuthenticated]  # User must be authenticated

    def post(self, request, *args, **kwargs):

        user = request.user  # Get the currently logged-in user
        current_password = request.data.get("current_password")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        # Validate required fields
        if not current_password:
            return Response(
                {"message": "Current password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not new_password:
            return Response(
                {"message": "New password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not confirm_password:
            return Response(
                {"message": "Confirm password is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if new password matches confirmation password
        if new_password != confirm_password:
            return Response(
                {"message": "New password and confirm password do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate the current password
        if not check_password(current_password, user.password):
            return Response(
                {"message": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate new password strength (optional)
        if len(new_password) < 8:
            return Response(
                {"message": "New password must be at least 8 characters long."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Update the user's password
            user.password = make_password(new_password)  # Hash the new password
            user.save()

            return Response(
                {"message": "Password has been successfully updated."},
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {"message": f"An unexpected error occurred: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class UpdateUserInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        data = request.data

        user.username = data.get("username", user.username)
        user.avatar = data.get("avatar", user.avatar)  # Assuming avatar is stored in the profile model

        try:
            user.save()
            serializer = UserSerializer(user) 
            return Response({"message": "Profile updated successfully.","user": serializer.data}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"message": f"An error occurred: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

class AvatarUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get("avatar")

        if not file:
            return Response(
                {"message": "No file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        content_type = file.content_type.lower()
        if content_type == "image/jpg":
            content_type = "image/jpeg"  # Treat "image/jpg" as "image/jpeg"

        if content_type not in ALLOWED_IMAGE_TYPES:
            return Response({"message": "Invalid file type. Only JPEG, PNG, and WEBP allowed."}, status=400)

        # Validate file size
        if file.size > MAX_FILE_SIZE:
            return Response({"message": "File size exceeds 5MB limit."}, status=400)

        # Save the file to a public folder
        file_path = os.path.join("avatars", file.name)
        file_name = default_storage.save(file_path, file)
        # file_url = os.path.join(settings.MEDIA_URL, file_name)
        file_url = file_name

        return Response({"file_url": file_url}, status=status.HTTP_200_OK)

class ProjectImageUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        project_id = request.data.get("project_id")
        file = request.FILES.get("image")

        if not project_id or not file:
            return Response({"message": "Project ID and image are required."}, status=status.HTTP_400_BAD_REQUEST)

        content_type = file.content_type.lower()
        if content_type == "image/jpg":
            content_type = "image/jpeg"  # Treat "image/jpg" as "image/jpeg"

        if content_type not in ALLOWED_IMAGE_TYPES:
            return Response({"message": "Invalid file type. Only JPEG, PNG, and WEBP allowed."}, status=400)

        # Validate file size
        if file.size > MAX_FILE_SIZE:
            return Response({"message": "File size exceeds 5MB limit."}, status=400)


        file_path = default_storage.save(f"project_images/{file.name}", file)
        file_url = file_path

        # Find the project
        project = get_object_or_404(ProjectModel, id=project_id)

        project.cover_image_url = file_url
        project.save()

        return Response({"file_url": file_url}, status=status.HTTP_200_OK)

class ProfileViewSet(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        try:
            user = UserModel.objects.get(id=request.user.id)
            serializer = UserSerializer(user)
            return Response(
                {"status": "success", "data": serializer.data},
                status=status.HTTP_200_OK,
            )
        except:
            return Response(
                {"status": "error", "data": ""}, status=status.HTTP_400_BAD_REQUEST
            )

    def put(self, request):
        try:
            user = UserModel.objects.get(id=request.user.id)
            serializer = UserSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(
                    {"status": "success", "data": serializer.data},
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"status": "error", "data": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except:
            return Response(
                {"status": "error", "data": ""}, status=status.HTTP_400_BAD_REQUEST
            )
            

class AdminSyncAllProjectAPIView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, *args, **kwargs):
        try:
            # Fetch the first and second API keys
            first_key = os.environ.get("ZENUS_API_KEY_1")
            second_key = os.environ.get("ZENUS_API_KEY_2")
            
            # Check if the first API key is missing
            if first_key:
                # Use the first API key initially
                os.environ["ZENUS_API_KEY"] = first_key
                print("Start sync with first API key")
                call_command('sync_zenus_data')  # Sync data with the first key
            else: print("ZENUS_API_KEY_1 is missing in environment variables.")

            # Check if the second API key is missing
            if second_key:
                # Switch to the second API key
                os.environ["ZENUS_API_KEY"] = second_key
                print("Start sync with seconde API key")
                call_command('sync_zenus_data')  # Sync data with the second key
            else: print("ZENUS_API_KEY_2 is missing in environment variables.")

            return Response({"status": "Data sync completed with both API keys."}, status=200)

        except Exception as e:
            return Response({"error": str(e)}, status=400)  

class AdminSyncProjectListAPIView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, *args, **kwargs):
        try:
            first_key = os.environ.get("ZENUS_API_KEY_1")
            second_key = os.environ.get("ZENUS_API_KEY_2")

            if not first_key and not second_key:
                return JsonResponse({"error": "No valid API keys found."}, status=400)

            projects = []

            if first_key:
                os.environ["ZENUS_API_KEY"] = first_key
                print("Syncing project list with first API key...")
                projects += sync_project_list()  # Accumulate projects from first key

            if second_key:
                os.environ["ZENUS_API_KEY"] = second_key
                print("Syncing project list with second API key...")
                projects += sync_project_list()  # Accumulate projects from second key

            if not projects:
                return JsonResponse({"error": "No projects synced."}, status=400)

            return JsonResponse({"status": "Sync completed.", "projects": [project['id'] for project in projects]})

        except Exception as e:
            print(f"Error during sync: {str(e)}")
            return JsonResponse({"error": "An error occurred during sync. Please check the server logs."}, status=400)

# View to sync a single project based on project_id
class AdminSyncOneProjectAPIView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, project_id, *args, **kwargs):
        try:
            first_key = os.environ.get("ZENUS_API_KEY_1")
            second_key = os.environ.get("ZENUS_API_KEY_2")

            project = None

            if first_key:
                os.environ["ZENUS_API_KEY"] = first_key
                print(f"Syncing project {project_id} with first API key...")
                project = sync_single_project(project_id)

            if second_key and not project:
                os.environ["ZENUS_API_KEY"] = second_key
                print(f"Syncing project {project_id} with second API key...")
                project = sync_single_project(project_id)

            if project:
                return JsonResponse({"status": "Sync completed.", "project": project.id})
            else:
                return JsonResponse({"error": "Project not found."}, status=404)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
           
class ProjectListAPIView(generics.ListAPIView):
    queryset = ProjectModel.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]  # requires authentication

    def get(self, request):
        try:
            user = request.user

            # base queryset of active projects
            qs = ProjectModel.objects.filter(is_active=True)

            # non-staff users only get their assigned projects
            if not (user.is_staff or user.is_superuser):
                assigned = getattr(user, "assigned_project_ids", []) or []
                qs = qs.filter(id__in=assigned)

            qs = qs.order_by("-id")

            # serialize projects
            serializer = ProjectSerializer(qs, many=True)
            project_data = serializer.data

            # fetch and map summaries
            summaries = SummaryModel.objects.filter(project__in=qs)
            summary_map = {s.project.id: s.content for s in summaries}
            for proj in project_data:
                proj["summary"] = summary_map.get(proj["id"], None)

            return Response(
                {"status": "success", "projects": project_data},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request):
        try:
            project_id = request.data.get("project_id")
            project = get_object_or_404(ProjectModel, id=project_id)
            serializer = ProjectSerializer(project)

            # Get sessions for the specified project
            sessions = SessionModel.objects.filter(project_id=project_id)

            # Fetch related project stages
            project_stages = ProjectStageModel.objects.filter(project_id=project_id)
            
            # Fetch related booths for the specified project
            booths = ProjectBoothModel.objects.filter(project_id=project_id)
            booth_serializer = ProjectBoothSerializer(booths, many=True)

            # Group sessions by project_stage_id
            grouped_sessions = defaultdict(list)
            for session in sessions:
                grouped_sessions[session.project_stage_id].append({
                    "id": session.id,
                    "name": session.name,
                    "start_datetime": session.start_datetime,
                    "video_start_datetime": session.video_start_datetime,
                    "video_end_datetime": session.video_end_datetime,
                    "end_datetime": session.end_datetime,
                    "video_url": session.video_url
                })

            # Prepare response with project stages and associated sessions
            stages = []
            for stage in project_stages:
                stages.append({
                    "project_stage_id": stage.id,
                    "project_stage_name": stage.name,
                    "project_stage_type": stage.type,
                    "sessions": grouped_sessions.get(stage.id, [])  # Include sessions if they exist
                })

            return Response({"status": "success", "stages": stages, "project": serializer.data, "booths": booth_serializer.data}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_queryset(self):
        """
        Optionally, you can prefetch related data to optimize SQL queries
        """
        return (
            ProjectModel.objects
            .prefetch_related('stages__sessions')
        )
    
class ProjectAnalyticsListAPIView(generics.ListAPIView):
    """
    API view to list all projects with their session analytics
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Modify this to filter based on your requirement
        return ProjectModel.objects.filter(is_active=True)

    def get(self, request, *args, **kwargs):
        projects = self.get_queryset()
        project_data = []

        for project in projects:
            # Get all session analytics for the current project
            session_analytics = SessionAnalyticsModel.objects.filter(project=project)
            
            # Initialize variables to accumulate the sum of each metric
            total_count = session_analytics.count()
            if total_count == 0:
                obs_average_analytics  = {
                    "male_ratio": 0,
                    "female_ratio": 0,
                    "under_40_ratio": 0,
                    "over_40_ratio": 0,
                    "energy_avg": 0,
                    "male_energy_avg": 0,
                    "female_energy_avg": 0,
                    "under_40_energy_avg": 0,
                    "over_40_energy_avg": 0,
                }
            else:
                # Accumulate the values for all session analytics
                sum_analytics = {
                    "male_ratio": 0,
                    "female_ratio": 0,
                    "under_40_ratio": 0,
                    "over_40_ratio": 0,
                    "energy_avg": 0,
                    "male_energy_avg": 0,
                    "female_energy_avg": 0,
                    "under_40_energy_avg": 0,
                    "over_40_energy_avg": 0,
                }

                for analytics in session_analytics:
                    sum_analytics["male_ratio"] += analytics.male_ratio or 0
                    sum_analytics["female_ratio"] += analytics.female_ratio or 0
                    sum_analytics["under_40_ratio"] += analytics.under_40_ratio or 0
                    sum_analytics["over_40_ratio"] += analytics.over_40_ratio or 0
                    sum_analytics["energy_avg"] += analytics.energy_avg or 0
                    sum_analytics["male_energy_avg"] += analytics.male_energy_avg or 0
                    sum_analytics["female_energy_avg"] += analytics.female_energy_avg or 0
                    sum_analytics["under_40_energy_avg"] += analytics.under_40_energy_avg or 0
                    sum_analytics["over_40_energy_avg"] += analytics.over_40_energy_avg or 0

                # Calculate the averages
                obs_average_analytics = {
                    "male_ratio": (sum_analytics["male_ratio"] / total_count) * 100,
                    "female_ratio": (sum_analytics["female_ratio"] / total_count) * 100,
                    "under_40_ratio": (sum_analytics["under_40_ratio"] / total_count) * 100,
                    "over_40_ratio": (sum_analytics["over_40_ratio"] / total_count) * 100,
                    "energy_avg": (sum_analytics["energy_avg"] / total_count) * 100,
                    "male_energy_avg": (sum_analytics["male_energy_avg"] / total_count) * 100,
                    "female_energy_avg": (sum_analytics["female_energy_avg"] / total_count) * 100,
                    "under_40_energy_avg": (sum_analytics["under_40_energy_avg"] / total_count) * 100,
                    "over_40_energy_avg": (sum_analytics["over_40_energy_avg"] / total_count) * 100,
                }

            booth_ids = list(project.booths.values_list('id', flat=True))

            if booth_ids:
                unique_analytics, impression_analytics = get_booth_impression_analytics(booth_ids)
            else:
                unique_analytics = {
                    "visits": 0, "dwell_visits": 0, "averageEnergy": 0, "averageDwellTime": "00:00:00"
                }
                impression_analytics = {
                    "total_impressions": 0, "stop_rate": 0,
                    "energy_avg": 0, "male_energy_avg": 0,
                    "female_energy_avg": 0, "under_40_energy_avg": 0,
                    "over_40_energy_avg": 0
                }
            
            project_sessions = SessionModel.objects.filter(project=project)

            if project_sessions.exists():
                qr_analytics = get_qr_analytics_for_project_sessions(project_sessions)
            else:
                qr_analytics = {
                    "total_qr_scans": 0,
                    "unique_qr_scans": 0,
                    "avg_dwell_time": 0,
                    "max_dwell_time": 0,
                    "unique_stage_qr_codes": {},
                }

            # Add the project data with calculated analytics
            project_data.append({
                "id": project.id,
                "name": project.name,
                "start_datetime": project.start_datetime,
                "end_datetime": project.end_datetime,
                "cover_image_url": project.cover_image_url.url if project.cover_image_url else None,
                "deployment_timezone": project.deployment_timezone,
                "is_ready": project.is_ready,
                "client_id": project.client.id if project.client else None,
                "type": project.type,
                "unique_qr_codes": project.unique_qr_codes,
                "services": project.services,
                "country": project.country,
                "city": project.city,
                "obs_average_analytics": obs_average_analytics,
                "uniqueImpressionAnalytics": unique_analytics,
                "impressionAnalytics": impression_analytics,
                "qr_analytics": qr_analytics
            })

        return Response(project_data)

def get_booth_impression_analytics(booth_ids):
    # Prepare Unique Impression Analytics
    unique_impressions = UniqueImpressionModel.objects.filter(
        booth_id__in=booth_ids,
        is_staff=False,
        zone="internal"
    )
    unique_impressions_dwell = unique_impressions.filter(dwell_time__gt=60)

    unique_data = unique_impressions.aggregate(
        visits=Count('id'),
        average_energy=Avg('energy_median')
    )
    dwell_data = unique_impressions_dwell.aggregate(
        visits=Count('id'),
        average_dwell_time=Avg('dwell_time')
    )

    average_dwell_time = dwell_data['average_dwell_time'] or 0
    formatted_dwell_time = (
        f"{int(average_dwell_time // 3600):02}:"
        f"{int((average_dwell_time % 3600) // 60):02}:"
        f"{int(average_dwell_time % 60):02}"
    )

    uniqueImpressionAnalytics = {
        "visits": unique_data['visits'] or 0,
        "dwell_visits": dwell_data['visits'] or 0,
        "averageEnergy": unique_data['average_energy'] or 0,
        "averageDwellTime": formatted_dwell_time
    }

    # Impression Analytics
    all_device_impressions = []
    for booth_id in booth_ids:
        booth_impressions = ImpressionModel.objects.filter(
            booth_id=booth_id,
            zone="aisle"
        ).values('device_id').annotate(impression_count=Count('device_id'))

        most_frequent_device = max(booth_impressions, key=lambda x: x['impression_count'], default=None)

        if most_frequent_device:
            device_impressions = ImpressionModel.objects.filter(
                booth_id=booth_id,
                device_id=most_frequent_device['device_id'],
                zone="aisle"
            )
            all_device_impressions.extend(device_impressions)

    total_impressions = len(all_device_impressions)
    stop_rate = (
        len([i for i in all_device_impressions if i.dwell_time > 15]) / total_impressions
        if total_impressions > 0 else 0
    )

    def energy_avg_filtered(qs):
        return sum(i.energy_median for i in qs) / len(qs) if qs else 0

    impressionAnalytics = {
        "total_impressions": total_impressions,
        "stop_rate": stop_rate,
        "energy_avg": energy_avg_filtered(all_device_impressions),
        "male_energy_avg": energy_avg_filtered([i for i in all_device_impressions if i.biological_sex == 'male']),
        "female_energy_avg": energy_avg_filtered([i for i in all_device_impressions if i.biological_sex == 'female']),
        "under_40_energy_avg": energy_avg_filtered([i for i in all_device_impressions if i.biological_age == '20-39']),
        "over_40_energy_avg": energy_avg_filtered([i for i in all_device_impressions if i.biological_age in ['40-59', '60+']]),
    }

    return uniqueImpressionAnalytics, impressionAnalytics

def get_qr_analytics_for_project_sessions(sessions):
    qr_codes_queryset = QrCodeModel.objects.none()
    stage_qr_codes_map = {}

    for session in sessions:
        start_buffer = session.start_datetime - timedelta(minutes=30)
        end_buffer = session.end_datetime + timedelta(minutes=15)
        stage_name = session.project_stage.name
        stage_suffix = session.project_stage.name.split(" - ")[-1]

        qr_codes_project = QrCodeModel.objects.filter(
            project=session.project,
            device_name__icontains=stage_suffix,
            datetime__range=(start_buffer, end_buffer)
        )

        qr_codes_queryset = qr_codes_queryset | qr_codes_project

        if stage_name not in stage_qr_codes_map:
            stage_qr_codes_map[stage_name] = set()
        stage_qr_codes_map[stage_name].update(qr_codes_project.values_list("qr_code", flat=True))

    total_qr_codes = qr_codes_queryset.count()
    unique_qr_codes_set = set(qr_codes_queryset.values_list("qr_code", flat=True))

    dwell_time_per_day = (
        qr_codes_queryset.exclude(dwell_time=0)
        .values("datetime__date", "qr_code")
        .annotate(max_dwell_time=Max("dwell_time"))
    )

    dwell_time_sum_per_day = defaultdict(int)
    for item in dwell_time_per_day:
        dwell_time_sum_per_day[item["datetime__date"]] += item["max_dwell_time"]

    avg_dwell_time = int(dwell_time_per_day.aggregate(Avg("max_dwell_time"))["max_dwell_time__avg"] or 0)
    max_dwell_time = dwell_time_per_day.aggregate(Max("max_dwell_time"))["max_dwell_time__max"] or 0

    unique_stage_qr_codes = {
        stage: len(codes)
        for stage, codes in stage_qr_codes_map.items()
    }

    return {
        "total_qr_scans": total_qr_codes,
        "unique_qr_scans": len(unique_qr_codes_set),
        "avg_dwell_time": avg_dwell_time,
        "max_dwell_time": max_dwell_time,
        "unique_stage_qr_codes": unique_stage_qr_codes,
    }

class AdminProjectListAPIView(generics.ListAPIView):
    queryset = ProjectModel.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            projects = ProjectModel.objects.order_by("-id")
            serializer = ProjectSerializer(projects, many=True)

            # Fetch summaries for projects
            summaries = SummaryModel.objects.filter(project__in=projects)
            summary_dict = {summary.project.id: summary.content for summary in summaries}

            # Add summary data to each project
            project_data = serializer.data
            for project in project_data:
                project["summary"] = summary_dict.get(project["id"], None)

            return Response({"status": "success", "projects": project_data}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_queryset(self):
        """
        Optionally, you can prefetch related data to optimize SQL queries
        """
        return (
            ProjectModel.objects
            .prefetch_related('stages__sessions')
        )
    
class SessionListAPIView(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    queryset = SessionModel.objects.all()
    serializer_class = SessionSerializer

    def get(self, request, *args, **kwargs):
        # Retrieve all sessions
        sessions = self.get_queryset()
        serializer = self.get_serializer(sessions, many=True)  # Serialize the queryset with many=True
        return Response({"sessions": serializer.data})
    
class UpdateSessionVideoDatetimeAPIView(generics.UpdateAPIView):
    queryset = SessionModel.objects.all()
    serializer_class = SessionSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'id'  # Use session ID to look up the session

    def update(self, request, *args, **kwargs):
        """
        Update the video_start_datetime and video_end_datetime for a session.
        """
        session = self.get_object()
        video_start_datetime = request.data.get('video_start_datetime', None)
        video_end_datetime = request.data.get('video_end_datetime', None)

        if video_start_datetime:
            session.video_start_datetime = video_start_datetime
        if video_end_datetime:
            session.video_end_datetime = video_end_datetime

        session.save()

        # Serialize the session data and return the updated session
        serializer = self.get_serializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
# class ObservationsBySessionView(generics.ListAPIView):
#     """
#     Returns all Observation records for a given session_id (no pagination).
#     Example endpoint: GET /observations/session/<session_id>/
#     """
#     serializer_class = ObservationSerializer
#     permission_classes = [IsAuthenticated]
#     pagination_class = None  # <-- Disables DRF pagination

#     def get_queryset(self):
#         session_id = self.kwargs.get('session_id')

#         # Check if the session exists; raise 404 if it doesn't
#         if not SessionModel.objects.filter(id=session_id).exists():
#             raise Http404("Session not found.")

#         # Get all observations for the session
#         observations = ObservationModel.objects.filter(session_id=session_id)

class ObservationsBySessionView(generics.ListAPIView):
    """
    Returns all Observation records for a given session_id, grouped by minute,
    with averages calculated for specific fields (no pagination).
    Example endpoint: GET /observations/session/<session_id>/
    """
    serializer_class = ObservationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None  # Disable pagination

    def get_queryset(self):
        session_id = self.kwargs.get('session_id')

        # Check if the session exists; raise 404 if it doesn't
        if not SessionModel.objects.filter(id=session_id).exists():
            raise Http404("Session not found.")

        # Get all observations for the session
        observations = ObservationModel.objects.filter(session_id=session_id)

        # Group by minute (rounding to the start of the minute)
        observations = observations.annotate(minute_group=TruncMinute('datetime'))

        # Aggregate average values per minute
        result = observations.values('minute_group').annotate(
            avg_energy=Avg('energy'),
            avg_energy_male=Avg('energy_male'),
            avg_energy_female=Avg('energy_female'),
            avg_energy_under_40=Avg('energy_under_40'),
            avg_energy_over_40=Avg('energy_over_40')
        ).order_by('minute_group')

        # Convert the results into ObservationModel instances (or data suitable for serialization)
        return result

class AdminSummaryViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for admin/staff users only.
    Pagination is disabled.
    """
    queryset = SummaryModel.objects.all()
    serializer_class = SummarySerializer
    permission_classes = [IsAuthenticated, IsStaffOrReviewer]
    pagination_class = None  # Disable pagination

    def create(self, request, *args, **kwargs):
        """Override create to return custom JSON."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"status": "success", "data": serializer.data},
            status=status.HTTP_201_CREATED
        )

    def perform_create(self, serializer):
        """If extra logic (e.g., set owner) is needed, do it here."""
        serializer.save()

    def list(self, request, *args, **kwargs):
        """Return a custom JSON response for the entire list."""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {"status": "success", "data": serializer.data},
            status=status.HTTP_200_OK
        )

    def retrieve(self, request, *args, **kwargs):
        """Return one specific summary object with custom JSON."""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {"status": "success", "data": serializer.data},
            status=status.HTTP_200_OK
        )

    def update(self, request, *args, **kwargs):
        """Full update (PUT) or partial update (PATCH)."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {"status": "success", "data": serializer.data},
            status=status.HTTP_200_OK
        )

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        """Delete a summary."""
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {"status": "success", "message": "Summary deleted successfully"},
            status=status.HTTP_200_OK
        )

    def perform_destroy(self, instance):
        instance.delete()

class SummaryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only endpoints for summaries.
    Must provide ?session=<id> or ?project=<id> to filter.
    """
    serializer_class = SummarySerializer
    permission_classes = [IsAuthenticated]
    queryset = SummaryModel.objects.all()
    pagination_class = None  # Disable pagination

    def get_queryset(self):
        queryset = super().get_queryset()
        session_id = self.request.query_params.get('session')
        project_id = self.request.query_params.get('project')

        if not session_id and not project_id:
            return queryset.none()  # Return empty if no filter

        if session_id:
            queryset = queryset.filter(session__id=session_id)
        if project_id:
            queryset = queryset.filter(project__id=project_id)

        return queryset

class CommentInfoView(generics.ListAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        session_id = request.query_params.get("session_id")
        if not session_id:
            return Response({"comments": [], "sentences": []})

        try:
            session = SessionModel.objects.get(id=session_id)
        except SessionModel.DoesNotExist:
            return Response({"comments": [], "sentences": []})

        comments = CommentModel.objects.filter(session_id=session_id).order_by("time")
        serializer = CommentSerializer(comments, many=True)

        return Response({
            "comments": serializer.data,
            "sentences": session.sentences or [],
        })

class CommentAddView(generics.CreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReviewer]

    def create(self, request, *args, **kwargs):
        user = request.user  # Get authenticated user
        data = request.data

        session_id = data.get("session")
        if not session_id:
            return Response({"error": "session_id is required."}, status=400)

        comment = CommentModel.objects.create(
            user=user,
            session_id=session_id,
            time=data.get("time"),
            content=data.get("content"),
        )

        serializer = CommentSerializer(comment)
        return Response({"message": "Comment added successfully", "comment": serializer.data}, status=201)

class CommentDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, IsStaffOrReviewer]

    def delete(self, request, *args, **kwargs):
        comment_id = kwargs.get("comment_id")
        comment = get_object_or_404(CommentModel, id=comment_id, user=request.user)

        comment.delete()
        return Response({"message": "Comment deleted successfully"}, status=status.HTTP_200_OK)

class SessionAnalyticsListAPIView(APIView):
    """
    Retrieve analytics data for multiple session IDs.
    Example usage:
    - GET /user/session-analytics-list?ids=1,2,3
    - POST /user/session-analytics-list/ { "session_ids": [1, 2, 3] }
    """
    permission_classes = [IsAuthenticated]

    # def get(self, request):
    #     """
    #     Handles GET request to fetch analytics for multiple session IDs.
    #     Example: GET /user/session-analytics-list?ids=1,2,3
    #     """
    #     session_ids = request.query_params.get("ids")

    #     if not session_ids:
    #         return Response({"message": "Session IDs are required."}, status=status.HTTP_400_BAD_REQUEST)

    #     session_ids = [int(id) for id in session_ids.split(",")]

    #     return self._fetch_analytics_data(session_ids)

    def post(self, request):
        """
        Handles POST request to fetch analytics for multiple session IDs.
        Example: POST /user/session-analytics-list/ { "session_ids": [1, 2, 3] }
        """
        session_ids = request.data.get("session_ids", [])

        # if not session_ids or not isinstance(session_ids, list):
        #     return Response(
        #         {"message": "Invalid session IDs. Provide an array of session IDs."},
        #         status=status.HTTP_400_BAD_REQUEST
        #     )

        return self._fetch_analytics_data(session_ids)

    def _fetch_analytics_data(self, session_ids):
        """
        Internal method to fetch session analytics based on session IDs.
        """
        analytics = SessionAnalyticsModel.objects.filter(session_id__in=session_ids)
        serializer = SessionAnalyticsSerializer(analytics, many=True)

        return Response({"status": "success", "analytics": serializer.data}, status=status.HTTP_200_OK)
    
class ImpressionTotalAnalyticsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Handles GET request to retrieve impression analytics for a given project_id.
        """
        # Get project_id from query parameters (not request body)
        project_id = request.query_params.get('project_id')

        if not project_id:
            raise serializers.ValidationError("Project ID is required.")

        try:
            # Ensure project_id is an integer
            project_id = int(project_id)

            # Retrieve the impression analytics for the given project_id and zones
            impression_analytics = ImpressionAnalyticsModel.objects.filter(
                project_id=project_id, zone__in=["internal", "aisle"]
            )

            if not impression_analytics.exists():
                return Response(
                    {"detail": "No impression analytics found for this project."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Serialize the data
            serializer = ImpressionAnalyticsSerializer(impression_analytics, many=True)

            return Response(serializer.data, status=status.HTTP_200_OK)

        except ValueError:
            return Response({"detail": "Invalid project ID format."}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            # Handling any unexpected errors
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ImpressionDetailAnalyticsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Handles GET request to retrieve unique impression analytics for given booth_ids.
        Returns visits, averageEnergy, and averageDwellTime.
        """
        booth_ids = request.query_params.getlist('booth_ids')  # Retrieve booth_ids from frontend
        
        if not booth_ids:
            return Response(
                {"detail": "Booth IDs are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Handle case where booth_ids may contain comma-separated values
            all_booth_ids = []
            for booth_id in booth_ids:
                # Split the comma-separated values and extend the list
                all_booth_ids.extend(booth_id.split(','))

            # Ensure booth_ids is a list of integers
            try:
                all_booth_ids = [int(booth_id) for booth_id in all_booth_ids]
            except ValueError:
                return Response(
                    {"detail": "One or more booth IDs are not valid integers."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # for unique_impression analytics
            # Retrieve UniqueImpressions for the given booth_ids with additional filters
            unique_impressions = UniqueImpressionModel.objects.filter(
                booth_id__in=all_booth_ids,
                is_staff=False,
                zone="internal"
            )
            if not unique_impressions.exists():
                return Response(
                    {"detail": "No unique impressions found for the given booth IDs."},
                    status=status.HTTP_404_NOT_FOUND
                )
            unique_impressions_dwell = unique_impressions.filter(dwell_time__gt=60)

            # Calculate the required fields
            unique_impression_data = unique_impressions.aggregate(
                visits=Count('id'),  # Count the number of records (visits)
                average_energy=Avg('energy_median'),  # Average of energy_median
            )

            unique_impression_data_dwell = unique_impressions_dwell.aggregate(
                visits=Count('id'),
                average_dwell_time=Avg('dwell_time')  # Average of dwell_time
            )

            # Format the average dwell time to hh:mm:ss
            average_dwell_time = unique_impression_data_dwell['average_dwell_time']

            if average_dwell_time:
                # Convert seconds to hh:mm:ss format
                hours = average_dwell_time // 3600
                minutes = (average_dwell_time % 3600) // 60
                seconds = average_dwell_time % 60
                formatted_dwell_time = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
            else:
                formatted_dwell_time = "00:00:00"

            # Prepare the response data
            uniqueImpressionAnalytics = {
                "visits": unique_impression_data['visits'],
                "dwell_visits": unique_impression_data_dwell['visits'],
                "averageEnergy": unique_impression_data['average_energy'],
                "averageDwellTime": formatted_dwell_time
            }

            impressionAnalytics = {
                "total_impressions": 0,
                "stop_rate": 0,
                "energy_avg": 0,
                "male_energy_avg": 0,
                "female_energy_avg": 0,
                "under_40_energy_avg": 0,
                "over_40_energy_avg": 0,
            }

            all_device_impressions = []

            # Loop through each booth_id to gather all impressions for each device_id
            for booth_id in all_booth_ids:
                # Group by device_id within each booth and get the device_id with the most impressions
                booth_impressions = ImpressionModel.objects.filter(
                    booth_id=booth_id,
                    zone="aisle"
                ).values('device_id').annotate(impression_count=Count('device_id'))

                most_frequent_device = max(booth_impressions, key=lambda x: x['impression_count'], default=None)

                if most_frequent_device:
                    device_id = most_frequent_device['device_id']
                    # Retrieve all impressions for this device_id in the current booth
                    device_impressions = ImpressionModel.objects.filter(
                        booth_id=booth_id,
                        device_id=device_id,
                        zone="aisle"
                    )

                    # Add impressions from this booth to the all_device_impressions list
                    all_device_impressions.extend(device_impressions)

            total_impressions = len(all_device_impressions)

            if total_impressions > 0:
                # Stop rate: impressions with dwell_time > 15
                impressions_with_dwell_gt_15 = len([imp for imp in all_device_impressions if imp.dwell_time > 15])
                stop_rate = impressions_with_dwell_gt_15 / total_impressions if total_impressions > 0 else 0

                # Average energy (total impressions)
                try:
                    energy_avg = sum(imp.energy_median for imp in all_device_impressions) / total_impressions
                except ZeroDivisionError:
                    energy_avg = 0  # Handle case where there might be no impressions

                # Male energy avg
                try:
                    male_impressions = [imp for imp in all_device_impressions if imp.biological_sex == 'male']
                    male_energy_avg = sum(imp.energy_median for imp in male_impressions) / len(male_impressions) if len(male_impressions) > 0 else 0
                except ZeroDivisionError:
                    male_energy_avg = 0

                # Female energy avg
                try:
                    female_impressions = [imp for imp in all_device_impressions if imp.biological_sex == 'female']
                    female_energy_avg = sum(imp.energy_median for imp in female_impressions) / len(female_impressions) if len(female_impressions) > 0 else 0
                except ZeroDivisionError:
                    female_energy_avg = 0

                # Under 40 energy avg
                try:
                    under_40_impressions = [imp for imp in all_device_impressions if imp.biological_age in ["20-39"]]
                    under_40_energy_avg = sum(imp.energy_median for imp in under_40_impressions) / len(under_40_impressions) if len(under_40_impressions) > 0 else 0
                except ZeroDivisionError:
                    under_40_energy_avg = 0

                # Over 40 energy avg
                try:
                    over_40_impressions = [imp for imp in all_device_impressions if imp.biological_age in ["40-59", "60+"]]
                    over_40_energy_avg = sum(imp.energy_median for imp in over_40_impressions) / len(over_40_impressions) if len(over_40_impressions) > 0 else 0
                except ZeroDivisionError:
                    over_40_energy_avg = 0

                impressionAnalytics = {
                    "total_impressions": total_impressions,
                    "stop_rate": stop_rate,
                    "energy_avg": energy_avg,
                    "male_energy_avg": male_energy_avg,
                    "female_energy_avg": female_energy_avg,
                    "under_40_energy_avg": under_40_energy_avg,
                    "over_40_energy_avg": over_40_energy_avg,
                }
            else:
                impressionAnalytics = {
                    "total_impressions": 0,
                    "stop_rate": 0,
                    "energy_avg": 0,
                    "male_energy_avg": 0,
                    "female_energy_avg": 0,
                    "under_40_energy_avg": 0,
                    "over_40_energy_avg": 0,
                }

            data = {
                "uniqueImpressionAnalytics": uniqueImpressionAnalytics,
                "impressionAnalytics": impressionAnalytics
            }

            return Response(data, status=status.HTTP_200_OK)

        except ValueError:
            return Response(
                {"detail": "Invalid booth ID format."},
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            # Handling any unexpected errors
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ClientViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    queryset = ClientModel.objects.annotate(
        lower_name=Lower('name')
    ).order_by('lower_name')
    serializer_class = ClientSerializer
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        client = self.get_object()
        
        # Set client_id to NULL in projects before deleting the client
        ProjectModel.objects.filter(client=client).update(client=None)
        
        # Proceed with deleting the client
        response = super().destroy(request, *args, **kwargs)
        
        return Response(
            {"status": "success", "message": "Client deleted successfully and associated projects updated."}, 
            status=status.HTTP_200_OK
        )

class ClientListAPIView(generics.ListAPIView):
    queryset = ClientModel.objects.annotate(
        lower_name=Lower('name')
    ).order_by('lower_name')
    serializer_class = ClientSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated]

class TemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    queryset = AITemplateModel.objects.all().order_by('-created_at')
    serializer_class = AITemplateSerializer
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        
        # Proceed with deleting the template
        response = super().destroy(request, *args, **kwargs)
        
        return Response(
            {"status": "success", "message": "Template deleted successfully and associated projects updated."}, 
            status=status.HTTP_200_OK
        )

class TemplateListAPIView(generics.ListAPIView):
    queryset = AITemplateModel.objects.all().order_by('-created_at')
    serializer_class = AITemplateSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated]
    
class SendContactEmail(APIView):
    permission_classes = []  # Public access allowed

    def post(self, request):
        try:
            # Extract form data from request
            data = request.data
            first_name = data.get("firstName")
            last_name = data.get("lastName")
            email = data.get("email")
            inquiry_type = data.get("inquiryType")
            message = data.get("message")

            if not (first_name and last_name and email and inquiry_type and message):
                return Response({"error": "All fields are required."}, status=status.HTTP_400_BAD_REQUEST)

            # Construct email content
            subject = f"New Contact Form Submission - {inquiry_type}"
            email_body = f"""
            New contact form submission:

            Name: {first_name} {last_name}
            Email: {email}
            Inquiry Type: {inquiry_type}

            Message:
            {message}
            """

            # Send email using Resend API
            resend.Emails.send({
                "from": "noreply@nonamegroup.com",
                "to": [support_email],
                "subject": subject,
                "text": email_body,
            })

            return Response({"success": True, "message": "Email sent successfully."}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class QrAnalyticsListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = QrAnalyticsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_ids = serializer.validated_data["session_ids"]

        sessions = SessionModel.objects.filter(id__in=session_ids)

        qr_codes_queryset = QrCodeModel.objects.none()
        stage_qr_codes_map = {}
        
        for session in sessions:
            start_buffer = session.start_datetime - timedelta(minutes=30)
            end_buffer = session.end_datetime + timedelta(minutes=15)

            # Get the stage name of the session
            stage_name = session.project_stage.name
            stage_suffix = session.project_stage.name.split(" - ")[-1]

            # Filter QrCodeModel based on project and device_name containing stage_name
            qr_codes_project = QrCodeModel.objects.filter(
                project=session.project,
                device_name__icontains=stage_suffix,  # Ensure device_name contains the stage name
                datetime__range=(start_buffer, end_buffer)
            )
            ##########################################(this is code for deviceModel's stage)
            # device_names = ProjectDeviceModel.objects.filter(stage__name=stage_name).values_list('name', flat=True)

            # # Filter QrCodeModel based on project and device_name containing stage_name
            # qr_codes_project = QrCodeModel.objects.filter(
            #     project=session.project,
            #     device_name__in=device_names,  # Ensures device_name matches an actual device
            #     datetime__range=(start_buffer, end_buffer)
            # )
            ###########################################
            qr_codes_queryset = qr_codes_queryset | qr_codes_project

            if stage_name not in stage_qr_codes_map:
                stage_qr_codes_map[stage_name] = set()

            stage_qr_codes_map[stage_name].update(qr_codes_project.values_list("qr_code", flat=True))

        total_qr_codes = qr_codes_queryset.count()
        unique_qr_codes_set = set(qr_codes_queryset.values_list("qr_code", flat=True))

        # Group by date and count total and unique scans per day
        qr_scans_per_day = (
            qr_codes_queryset
            .values("datetime__date")
            .annotate(
                total_qr_scans_day=Count("id"),
                unique_qr_scans_day=Count("qr_code", distinct=True)
            )
        )
        qr_scans_day_list = [
            {"date": item["datetime__date"].strftime("%Y-%m-%d"), "total": item["total_qr_scans_day"], "unique": item["unique_qr_scans_day"]}
            for item in qr_scans_per_day
        ]

        # Sum max dwell times per QR code per date
        dwell_time_per_day = (
            qr_codes_queryset.exclude(dwell_time=0)
            .values("datetime__date", "qr_code")
            .annotate(max_dwell_time=Max("dwell_time"))
        )

        dwell_time_sum_per_day = defaultdict(int)
        for item in dwell_time_per_day:
            dwell_time_sum_per_day[item["datetime__date"]] += item["max_dwell_time"]

        dwell_time_list = [
            {"date": date.strftime("%Y-%m-%d"), "sum_dwell_time": dwell_time_sum_per_day[date]}
            for date in dwell_time_sum_per_day
        ]

        # Unique QR codes per minute
        qr_codes_per_minute = (
            qr_codes_queryset
            .annotate(minute=TruncMinute("datetime"))
            .values("minute")
            .annotate(unique_qr_codes_min=Count("qr_code", distinct=True))
        )

        # qr_codes_per_10_min = defaultdict(int)
        # for item in qr_codes_per_minute:
        #     minute = item["minute"]
        #     ten_min_group = minute.replace(minute=(minute.minute // 10) * 10)
        #     qr_codes_per_10_min[ten_min_group] = max(qr_codes_per_10_min[ten_min_group], item["unique_qr_codes_min"])

        unique_qr_codes_per_min_list = [
            {"datetime": item["minute"], "unique_qr_codes": item["unique_qr_codes_min"]}
            for item in qr_codes_per_minute
        ]

        # unique_qr_codes_per_10_min_list = [
        #     {"datetime": time, "unique_qr_codes": count}
        #     for time, count in qr_codes_per_10_min.items()
        # ]

        avg_dwell_time = int(dwell_time_per_day.aggregate(Avg("dwell_time"))["dwell_time__avg"] or 0)
        max_dwell_time = dwell_time_per_day.aggregate(Max("dwell_time"))["dwell_time__max"] or 0

        # Calculate unique QR codes per stage
        unique_stage_qr_codes = {
            stage: len(qr_codes)
            for stage, qr_codes in stage_qr_codes_map.items()
        }

        response_data = {
            "total_qr_scans": total_qr_codes,
            "unique_qr_scans": len(unique_qr_codes_set),
            "avg_dwell_time": avg_dwell_time,
            "max_dwell_time": max_dwell_time,
            "unique_stage_qr_codes": unique_stage_qr_codes,
            "qr_scans_day_list": qr_scans_day_list,
            "dwell_time_list": dwell_time_list,
            "unique_qr_codes_per_min_list": unique_qr_codes_per_min_list,
            # "unique_qr_codes_per_10_min_list": unique_qr_codes_per_10_min_list,
        }

        response_serializer = QrAnalyticsResponseSerializer(response_data)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AdminAssignUserProjectsView(APIView):
    permission_classes = [IsStaffOrSuperAdmin]
    
    def get(self, request, user_id):
        try:
            user = UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {"assigned_project_ids": user.assigned_project_ids},
            status=status.HTTP_200_OK,
        )

    def patch(self, request, user_id):
        project_ids = request.data.get("project_ids")
        if not isinstance(project_ids, list):
            return Response(
                {"error": "project_ids list required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        user.assigned_project_ids = project_ids
        user.save()
        return Response(
            {"assigned_project_ids": user.assigned_project_ids},
            status=status.HTTP_200_OK,
        )
