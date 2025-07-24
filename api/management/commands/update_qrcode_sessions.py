from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from api.models import QrCodeModel, SessionModel

class Command(BaseCommand):
    help = "Update the session_id for all QrCodeModel objects based on the new buffer rules."

    def handle(self, *args, **options):
        """
        Loops over all QrCodeModel objects and updates
        its session field if it fits within:
            session.start_datetime - 30 mins <= qr.datetime <= session.end_datetime + 15 mins
        """
        # Fetch all QrCodeModel rows, or you could filter to only those without a session.
        all_qrs = QrCodeModel.objects.all()

        updated_count = 0

        for qr_obj in all_qrs:
            # Possibly convert qr_obj.datetime to aware datetime if needed.
            # Typically, QrCodeModel.datetime is already timezone-aware, but double-check:
            dt = qr_obj.datetime
            if dt and dt.tzinfo is None:
                dt = timezone.make_aware(dt)

            # Find sessions in the same project
            sessions = SessionModel.objects.filter(project=qr_obj.project)

            matched_session = None
            for session in sessions:
                start_with_buffer = session.start_datetime - timedelta(minutes=30)
                end_with_buffer = session.end_datetime + timedelta(minutes=15)

                if start_with_buffer <= dt <= end_with_buffer:
                    matched_session = session
                    break

            if matched_session is not None:
                # If a session was found and it's different from what is currently stored
                if qr_obj.session_id != matched_session.id:
                    qr_obj.session = matched_session
                    qr_obj.save()
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Done! Updated session on {updated_count} QR code records.")
        )
