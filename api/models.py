from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
import datetime
from django.utils.timezone import now
from datetime import timedelta

# Create your models here.

class UserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **kwargs):
        if username is None:
            raise TypeError("Users must have a username.")
        if email is None:
            raise TypeError("Users must have an email.")

        user = self.model(
            username=username,
            email=self.normalize_email(email),
        )
        user.set_password(password)
        user.save(using=self._db)

        return user
    

class UserModel(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(db_index=True, max_length=150)
    email = models.EmailField(db_index=True, unique=True, null=True, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True, max_length=255)
    is_staff = models.BooleanField(default=False)
    is_reviewer = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    assigned_project_ids = models.JSONField(default=list, blank=True)
    email_verified = models.BooleanField(default=False)
    created = models.DateField(default=datetime.date.today)
    updated = models.DateField(default=datetime.date.today)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(default=now, blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()


    def __str__(self):
        return f"{self.email}"

def get_default_expiration():
    return now() + timedelta(hours=1)

    
class VerificationTokenModel(models.Model):
    email = models.EmailField(unique=True)
    token = models.CharField(max_length=255, unique=True)
    expires = models.DateTimeField(default=get_default_expiration)

    class Meta:
        unique_together = ('email', 'token')

    def __str__(self):
        return f"VerificationTokenModel(email={self.email}, token={self.token})"

class ResetPasswordTokenModel(models.Model):
    email = models.EmailField(unique=True)
    token = models.CharField(max_length=255, unique=True)
    expires = models.DateTimeField(default=get_default_expiration)

    class Meta:
        unique_together = ('email', 'token')

    def __str__(self):
        return f"ResetPasswordTokenModel(email={self.email}, token={self.token})"

class ClientModel(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class AITemplateModel(models.Model):
    id = models.AutoField(primary_key=True)
    type = models.CharField(max_length=255, unique=True, default='HTML')
    template = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.type

class ProjectModel(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    cover_image_url = models.ImageField(upload_to="project_cover_images/", blank=True, null=True, max_length=255)
    deployment_timezone = models.CharField(max_length=100)
    is_ready = models.BooleanField(default=False)  # New field for additional data
    is_active = models.BooleanField(default=False)
    client = models.ForeignKey(ClientModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects")
    type = models.JSONField(default=list, blank=True)
    unique_qr_codes = models.IntegerField(default=0)

    services = models.JSONField(default=list, blank=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name
    
class ProjectBoothModel(models.Model):
    id = models.AutoField(primary_key=True)
    booth_id = models.CharField(max_length=255, unique=True)  # Use booth ID as unique
    name = models.CharField(max_length=255)
    size = models.IntegerField()
    project = models.ForeignKey(ProjectModel, related_name="booths", on_delete=models.CASCADE)
    
    # New field to store operating hours as JSON
    operating_hours = models.JSONField(blank=True, null=True)

    def __str__(self):
        return self.name

class ProjectStageModel(models.Model):
    STAGE_TYPE_CHOICES = [
        ("obs", "Observation"),
        ("imp", "Impression"),
        ("qr", "QR Code"),
    ]

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    project = models.ForeignKey(ProjectModel, related_name="stages", on_delete=models.CASCADE)
    type = models.CharField(max_length=10, choices=STAGE_TYPE_CHOICES, null=True, blank=True)  # Store a single type

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"

class ProjectDeviceModel(models.Model):
    id = models.AutoField(primary_key=True)
    device_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    service = models.CharField(max_length=255)
    project = models.ForeignKey(ProjectModel, related_name="devices", on_delete=models.CASCADE)
    assignments = models.JSONField(blank=True, null=True)

    def __str__(self):
        return self.name

class SessionModel(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    video_start_datetime = models.DateTimeField(null=True, blank=True)
    video_end_datetime = models.DateTimeField(null=True, blank=True)
    video_url = models.TextField(null=True, blank=True)
    audio_url = models.TextField(null=True, blank=True)
    transcript = models.TextField(null=True, blank=True)
    sentences = models.JSONField(null=True, blank=True)
    project = models.ForeignKey(ProjectModel, related_name="sessions", on_delete=models.CASCADE)
    project_stage = models.ForeignKey(ProjectStageModel, related_name="sessions", on_delete=models.CASCADE)
    
    def __str__(self):
        return f"Session {self.id}"

class ImpressionModel(models.Model):
    latest_datetime = models.DateTimeField()
    device_id = models.CharField(max_length=255, null=True, blank=True)
    device_name = models.CharField(max_length=255, null=True, blank=True)
    zone = models.CharField(max_length=255, null=True, blank=True)
    dwell_time = models.FloatField()
    energy_median = models.FloatField()
    face_height_median = models.IntegerField()
    biological_sex = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female'), ('unknown', 'Unknown')])
    biological_age = models.CharField(max_length=100)
    
    project = models.ForeignKey(ProjectModel, related_name="impressions", on_delete=models.CASCADE)
    booth = models.ForeignKey(ProjectBoothModel, related_name="impressions", on_delete=models.CASCADE, null=True, blank=True)
    
    def __str__(self):
        return f"Impression for project {self.project.name} at {self.latest_datetime}"
    
class UniqueImpressionModel(models.Model):
    project = models.ForeignKey(ProjectModel, related_name="unique_impressions", on_delete=models.CASCADE)
    device_id = models.CharField(max_length=255)
    date = models.DateField()
    zone = models.CharField(max_length=50)
    is_staff = models.BooleanField()
    impressions_total = models.IntegerField()
    visit_duration = models.FloatField()
    dwell_time = models.FloatField()
    energy_median = models.FloatField()
    face_height_median = models.FloatField()
    biological_sex = models.CharField(max_length=20)
    biological_age = models.CharField(max_length=20)

    booth = models.ForeignKey(ProjectBoothModel, related_name="unique_impressions", on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"Impression on {self.date} for device {self.device_id} in {self.zone}"
        
class ImpressionAnalyticsModel(models.Model):
    project = models.ForeignKey(ProjectModel, related_name="impression_analytics", on_delete=models.CASCADE)
    date = models.JSONField()  # List of dates for the analytics
    impression_count = models.JSONField()  # List of dictionaries with time and impression count for each time interval
    total_impressions = models.IntegerField()  # Total number of impressions for the project
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    zone = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Impression Analytics for project {self.project.name} on {', '.join(self.date)}"

class ObservationModel(models.Model):
    datetime = models.DateTimeField()
    device_id = models.CharField(max_length=255, null=True, blank=True)
    device_name = models.CharField(max_length=255, null=True, blank=True)
    count_total = models.FloatField(null=True, blank=True)
    count_male = models.FloatField(null=True, blank=True)
    count_female = models.FloatField(null=True, blank=True)
    count_under_40 = models.FloatField(null=True, blank=True)
    count_over_40 = models.FloatField(null=True, blank=True)
    energy = models.FloatField(null=True, blank=True)
    energy_male = models.FloatField(null=True, blank=True)
    energy_female = models.FloatField(null=True, blank=True)
    energy_under_40 = models.FloatField(null=True, blank=True)
    energy_over_40 = models.FloatField(null=True, blank=True)

    project = models.ForeignKey(ProjectModel, related_name="observations", on_delete=models.CASCADE)
    session = models.ForeignKey(SessionModel, related_name="observations", on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"Observation for project {self.project.name} at {self.datetime}"


class QrCodeModel(models.Model):
    datetime = models.DateTimeField()
    device_id = models.CharField(max_length=255, null=True, blank=True)
    device_name = models.CharField(max_length=255, null=True, blank=True)
    qr_code = models.CharField(max_length=255)
    dwell_time = models.IntegerField(default=0, help_text="Dwell time in minutes")

    project = models.ForeignKey(ProjectModel, related_name="qr_codes", on_delete=models.CASCADE)
    session = models.ForeignKey(SessionModel, related_name="qr_codes", on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"Qr code for project {self.project.name} at {self.datetime}"

class SessionAnalyticsModel(models.Model):
    """
    Stores aggregated (session-level) demographic metrics:
      - Demographic ratios (male/female, under/over 40)
      - Average energies by demographic
    """
    project = models.ForeignKey(
        ProjectModel,
        on_delete=models.CASCADE,
        related_name="analytics"
    )
    session = models.ForeignKey(
        SessionModel,
        on_delete=models.CASCADE,
        related_name="analytics",
        null=True,  # Allow null for project-level analytics if needed
        blank=True
    )

    # Demographic Ratios
    male_ratio = models.FloatField(null=True, blank=True)
    female_ratio = models.FloatField(null=True, blank=True)
    under_40_ratio = models.FloatField(null=True, blank=True)
    over_40_ratio = models.FloatField(null=True, blank=True)

    # Average Energies
    energy_avg = models.FloatField(null=True, blank=True)
    male_energy_avg = models.FloatField(null=True, blank=True)
    female_energy_avg = models.FloatField(null=True, blank=True)
    under_40_energy_avg = models.FloatField(null=True, blank=True)
    over_40_energy_avg = models.FloatField(null=True, blank=True)

    # Timestamps for bookkeeping
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Analytics for {self.session.name} (Project: {self.project.name})"

class SummaryModel(models.Model):
    user = models.ForeignKey(
        UserModel,
        on_delete=models.CASCADE,
        related_name='summaries'
    )
    session = models.OneToOneField(
        SessionModel,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='summary'
    )
    project = models.OneToOneField(
        ProjectModel,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='summary'
    )
    content = models.TextField(null=True, blank=True)
    opportunity = models.CharField(max_length=255, null=True, blank=True) 
    challenge = models.CharField(max_length=255, null=True, blank=True)  
    action_step = models.CharField(max_length=255, null=True, blank=True) 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        base_str = f"Summary by {self.user.email}"
        if self.project:
            base_str += f" on {self.project.name}"
        if self.session:
            base_str += f" (Session {self.session.id})"
        return base_str + f" at {self.created_at}"

class CommentModel(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(UserModel, on_delete=models.CASCADE, related_name="comments")
    session = models.ForeignKey(SessionModel, on_delete=models.CASCADE, related_name="comments")
    time = models.CharField(max_length=20)  # Stores video timestamp (HH:MM:SS)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.content[:30]}"  # Show username & preview
