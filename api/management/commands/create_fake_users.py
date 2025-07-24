import random
from django.core.management.base import BaseCommand
from faker import Faker
from api.models import UserModel

class Command(BaseCommand):
    help = "Create 100 fake users"

    def handle(self, *args, **kwargs):
        fake = Faker()
        users = []
        
        for _ in range(100):
            username = fake.user_name()
            email = fake.unique.email()
            avatar = None  # Adjust this if you have actual avatars
            is_staff = random.choice([True, False])
            is_reviewer = random.choice([True, False])
            is_active = random.choice([True, False])
            email_verified = random.choice([True, False])
            
            user = UserModel(
                username=username,
                email=email,
                avatar=avatar,
                is_staff=is_staff,
                is_reviewer=is_reviewer,
                is_active=is_active,
                email_verified=email_verified,
            )
            user.set_password("password123")  # Set a default password
            users.append(user)
        
        UserModel.objects.bulk_create(users)
        self.stdout.write(self.style.SUCCESS("100 fake users created successfully!"))
