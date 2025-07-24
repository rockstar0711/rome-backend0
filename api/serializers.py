from .models import *
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings
from django.contrib.auth.models import update_last_login
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Prefetch

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        max_length=128, min_length=8, write_only=True, required=True
    )
    old_password = serializers.CharField(
        max_length=128, min_length=8, write_only=True, required=False
    )

    class Meta:
        model = UserModel
        fields = [
            "id",
            "username",
            "email",
            "avatar",
            "password",
            "old_password",
            "is_superuser",
            "is_staff",
            "is_reviewer",
            "is_active",
            "assigned_project_ids",
            "email_verified",
            "created",
            "updated",
        ]
        read_only_fields = ["created", "updated"]
        
    

    def create(self, validated_data):
        # Pop off raw password (if provided)
        raw_pwd = validated_data.pop("password", None)

        # Create user without the raw password field
        user = super().create(validated_data)

        # If admin provided a password, hash & save it
        if raw_pwd:
            user.set_password(raw_pwd)
            user.save(update_fields=["password"])

        return user

    def update(self, instance, validated_data):
        # Pop off raw password (if they want to change it)
        raw_pwd = validated_data.pop("password", None)

        # Let DRF handle the other fields
        user = super().update(instance, validated_data)

        # Hash & save new password if given
        if raw_pwd:
            user.set_password(raw_pwd)
            user.save(update_fields=["password"])

        return user


class RegisterSerializer(UserSerializer):
    password = serializers.CharField(
        max_length=128, min_length=8, write_only=True, required=True
    )
    
    class Meta:
        model = UserModel
        fields = [
            "id",
            "username",
            "email",
            "password",
            "avatar",
            "is_active",
            "is_superuser",
            "is_staff",
            "is_reviewer",
            "email_verified",
            "created",
            "updated",
        ]
        
    def validate(self, attrs):
        password  = attrs.get("password", "")
        if len(password) < 8:
            raise serializers.ValidationError("Passwords must be at least 8 characters!")

        return attrs
    
    def create(self, validated_data):
        try:
            user = UserModel.objects.get(email=validated_data["email"])
        except ObjectDoesNotExist:
            user = UserModel.objects.create_user(**validated_data)
        return user

class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        refresh = self.get_token(self.user)

        user_data = UserSerializer(self.user).data
        data["user"] = user_data
        data["refresh"] = str(refresh)
        data["access"] = str(refresh.access_token)
       
        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)

        return data

class SessionAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionAnalyticsModel
        fields = [
            'session_id',
            'male_ratio',
            'female_ratio',
            'under_40_ratio',
            'over_40_ratio',
            'energy_avg',
            'male_energy_avg',
            'female_energy_avg',
            'under_40_energy_avg',
            'over_40_energy_avg',
        ]

class ImpressionAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImpressionAnalyticsModel
        fields = [
            'id',
            'project',
            'zone',
            'date',
            'impression_count',
            'total_impressions',
            'created_at',
            'updated_at',
        ]

class UniqueImpressionAnalyticsSerializer(serializers.Serializer):
    visits = serializers.IntegerField()
    averageEnergy = serializers.FloatField()
    averageDwellTime = serializers.CharField()

class SessionForStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionModel
        fields = [
            'id',
            'name',
            'start_datetime',
            'end_datetime',
            'video_start_datetime',
            'video_end_datetime',
            'video_url',
            'project_stage',  # if you want stage ID or other reference
        ]

class StageSerializer(serializers.ModelSerializer):
    # nest sessions inside
    sessions = SessionForStageSerializer(many=True, read_only=True)

    class Meta:
        model = ProjectStageModel
        fields = [
            'id',
            'name',
            'sessions',
        ]

class ProjectForSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectModel
        fields = ['id', 'name']  # Only include id and name for project

class ProjectStageForSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectStageModel
        fields = ['id', 'name']  # Only include id and name for project stage

class SessionSerializer(serializers.ModelSerializer):
    project = ProjectForSessionSerializer(read_only=True)  # Include nested project details
    project_stage = ProjectStageForSessionSerializer(read_only=True)  # Include nested project stage details

    class Meta:
        model = SessionModel
        fields = [
            'id',
            'name',
            'start_datetime',
            'end_datetime',
            'video_start_datetime',
            'video_end_datetime',
            'video_url',
            'project',  # Nested project data with id and name
            'project_stage',  # Nested project stage data with id and name
        ]

class ProjectBoothSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectBoothModel
        fields = ['id', 'booth_id', 'name', 'size', 'operating_hours']

# class ObservationSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = ObservationModel
#         fields = '__all__'

class ObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ObservationModel
        fields = ['datetime', 'energy', 'energy_male', 'energy_female', 'energy_under_40', 'energy_over_40']

    # Adjust serializer to only include fields you want in the response
    def to_representation(self, instance):
        # For grouped data, you may need to manually format the output
        return {
            'datetime': instance['minute_group'],  # The rounded minute datetime
            'energy': instance['avg_energy'],
            'energy_male': instance['avg_energy_male'],
            'energy_female': instance['avg_energy_female'],
            'energy_under_40': instance['avg_energy_under_40'],
            'energy_over_40': instance['avg_energy_over_40'],
        }

class ProjectSerializer(serializers.ModelSerializer):
    stages = StageSerializer(many=True, read_only=True)
    client_id = serializers.PrimaryKeyRelatedField(
        source="client", queryset=ClientModel.objects.all(), allow_null=True, required=False
    )
    client_name = serializers.CharField(source="client.name", read_only=True)

    class Meta:
        model = ProjectModel
        fields = [
            'id',
            'name',
            'start_datetime',
            'end_datetime',
            'deployment_timezone',
            'cover_image_url',
            'city',
            'country',
            'is_ready',
            'is_active',
            'type',
            'unique_qr_codes',
            'client_id',
            'client_name',
            'stages',         # nested list of stages & sessions
        ]

class ProjectAnalyticsSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    start_datetime = serializers.DateTimeField()
    end_datetime = serializers.DateTimeField()
    cover_image_url = serializers.CharField()
    deployment_timezone = serializers.CharField()
    is_ready = serializers.BooleanField()
    client = serializers.CharField()
    type = serializers.ListField(child=serializers.CharField())
    unique_qr_codes = serializers.IntegerField()
    services = serializers.ListField(child=serializers.CharField())
    country = serializers.CharField()
    city = serializers.CharField()
    obs_average_analytics = serializers.DictField()

class SummarySerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_avatar = serializers.SerializerMethodField(read_only=True)
    session_name = serializers.CharField(source='session.name', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)

    class Meta:
        model = SummaryModel
        fields = [
            'id',
            'content',
            'opportunity',  
            'challenge',    
            'action_step',
            'created_at',
            'updated_at',
            'user',
            'session',
            'project',
            'user_email',
            'user_username',
            'user_avatar',
            'session_name',
            'project_name',
        ]

    def get_user_avatar(self, obj):
        """Returns the user's avatar URL if it exists, otherwise None"""
        if obj.user and obj.user.avatar:
            return obj.user.avatar.url
        return None
        
class CommentSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = CommentModel
        fields = ["id", "user", "session", "time", "content", "created_at"]

    def get_user(self, obj):
        """Returns user details including username and avatar."""
        return {
            "id": obj.user.id,
            "username": obj.user.username,
            "avatar_url": obj.user.avatar.url if obj.user.avatar else "",
        }


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientModel
        fields = ['id', 'name',]
        read_only_fields = ['id',]

class AITemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AITemplateModel
        fields = ['id', 'type', 'template',]

class QrAnalyticsRequestSerializer(serializers.Serializer):
    session_ids = serializers.ListField(child=serializers.IntegerField(), required=True)

class QrAnalyticsResponseSerializer(serializers.Serializer):
    total_qr_scans = serializers.IntegerField()
    unique_qr_scans = serializers.IntegerField()
    avg_dwell_time = serializers.FloatField()
    max_dwell_time = serializers.FloatField()
    unique_stage_qr_codes = serializers.DictField(child=serializers.IntegerField())
    qr_scans_day_list = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField(),  
            allow_empty=True
        )
    )
    dwell_time_list = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField(),  
            allow_empty=True
        )
    )
    unique_qr_codes_per_min_list = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField(),  
            allow_empty=True
        )
    )
    # unique_qr_codes_per_10_min_list = serializers.ListField(
    #     child=serializers.DictField(
    #         child=serializers.CharField(),
    #         allow_empty=True
    #     )
    # )
