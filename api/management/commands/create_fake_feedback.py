import random
from django.core.management.base import BaseCommand
from faker import Faker
from api.models import FeedbackModel

class Command(BaseCommand):
    help = "Create 50 fake feedback entries"

    def handle(self, *args, **kwargs):
        fake = Faker()
        feedbacks = []

        for _ in range(50):
            # Randomly choose between session_id=77 and project_id=354, making them mutually exclusive
            if random.choice([True, False]):
                session_id = 8
                project_id = None
            else:
                session_id = None
                project_id = 354

            # Generate each text field with a 20% chance of being None
            def generate_text():
                return fake.paragraph(nb_sentences=2) if random.random() < 0.8 else None

            summary = generate_text()
            opportunities = generate_text()
            challenges = generate_text()
            action_steps = generate_text()

            feedback = FeedbackModel(
                user_id=1,
                session_id=session_id,
                project_id=project_id,
                summary=summary,
                opportunities=opportunities,
                challenges=challenges,
                action_steps=action_steps
            )
            feedbacks.append(feedback)

        # Bulk create all feedback entries
        FeedbackModel.objects.bulk_create(feedbacks)

        self.stdout.write(self.style.SUCCESS("Successfully created 50 fake feedback entries"))