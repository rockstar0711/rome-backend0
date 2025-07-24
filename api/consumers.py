import json
from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer, AsyncWebsocketConsumer
from django.core.exceptions import ValidationError

class VideoUploadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = "video_upload_progress"  # Name of the group

        # Join the room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave the room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

    # Receive progress data from WebSocket
    async def send_progress(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event))

    # Helper method to send progress updates
    def send_progress_update(self, stage, progress):
        # Send a progress update to the room group
        self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'send_progress',
                'stage': stage,
                'progress': progress,
            }
        )
