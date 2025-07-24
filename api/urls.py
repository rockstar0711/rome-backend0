from rest_framework.routers import SimpleRouter
from django.urls import path, include
from .views import *
from rest_framework.routers import DefaultRouter

routes = SimpleRouter()
default_router = DefaultRouter()

routes.register(r"auth/login", LoginViewSet, basename="auth-login")
routes.register(r"auth/register", RegisterationViewSet, basename="auth-register")
# routes.register(r"auth/logout", UserLogoutView, basename="auth-logout")
routes.register(r"auth/refresh", RefreshViewSet, basename="auth-refresh")

default_router.register(r'admin/clients', ClientViewSet, basename='clients')
default_router.register(r'admin/templates', TemplateViewSet, basename='templates')
default_router.register(r'admin/summaries', AdminSummaryViewSet, basename='admin-summaries')
default_router.register(r'user/summaries', SummaryViewSet, basename='summaries')

urlpatterns = [
    *routes.urls,
    path('', include(default_router.urls)),
    path("logout/", UserLogoutView.as_view(), name="logout-user"),
    path("admin/userlist", UserListViewSet.as_view(), name="userlist"),
    path("admin/user-action/", AdminUserActionViewSet.as_view(), name="useraction"),
    path("admin/match-action", AdminMatchActionView.as_view(), name='matchaction'),
    path('admin/get-presigned-url', GetPresignedUrlView.as_view(), name='get_presigned_url'),
    path("admin/update-project/", AdminUpdateProjectView.as_view(), name='update-project'),
    path("admin/upload-video/", AdminUploadVideoView.as_view(), name='upload-video'),
    path('admin/sync-all-project', AdminSyncAllProjectAPIView.as_view(), name='sync_all_project'),
    path("admin/users/<int:user_id>/projects/", AdminAssignUserProjectsView.as_view(), name="user-projects"),
    path('admin/sync-project-list', AdminSyncProjectListAPIView.as_view(), name='sync_project_list'),
    path('admin/sync-one-project/<int:project_id>/', AdminSyncOneProjectAPIView.as_view(), name='sync_one_project'),
    path("admin/upload-project-image/", ProjectImageUploadView.as_view(), name="upload-project-image"),
    path("auth/verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("auth/reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path('user/projects/', ProjectListAPIView.as_view(), name='user-project-list'),
    path('user/analytics-projects/', ProjectAnalyticsListAPIView.as_view(), name='user-analytics-project-list'),
    path('admin/projects/', AdminProjectListAPIView.as_view(), name='admin-project-list'),
    path('user/clients/', ClientListAPIView.as_view(), name='client-list'),
    path('user/templates/', TemplateListAPIView.as_view(), name='template-list'),
    path('admin/sessions/', SessionListAPIView.as_view(), name='session-list'),
    path('admin/update-session-video/<int:id>/', UpdateSessionVideoDatetimeAPIView.as_view(), name='update-session-video-datetime'),
    path("user/session-analytics-list/", SessionAnalyticsListAPIView.as_view(), name="session-analytics-list"),
    path('user/impression-total-analytics/', ImpressionTotalAnalyticsAPIView.as_view(), name="impression-total-analytics"),
    path('user/impression-detail-analytics/', ImpressionDetailAnalyticsAPIView.as_view(), name="impression-detail-analytics"),
    path("user/qr-analytics-list/", QrAnalyticsListAPIView.as_view(), name="qr-analytics-list"),
    path('user/observations/session/<int:session_id>/', ObservationsBySessionView.as_view(), name='observations-by-session'),
    path("profile/update-password/", UpdatePasswordView.as_view(), name="update-password"),
    path("profile/update-info/", UpdateUserInfoView.as_view(), name="update-user-info"),
    path("profile/upload-avatar/", AvatarUploadView.as_view(), name="upload-avatar"),
    path("profile", ProfileViewSet.as_view()),
    path("user/comments/", CommentInfoView.as_view(), name="get_comments"),  # GET request
    path("admin/comments/add", CommentAddView.as_view(), name="add_comment"),  # POST request
    path("admin/comments/delete/<int:comment_id>/", CommentDeleteView.as_view(), name="delete_comment"),
    path("pub/send-contact-email/", SendContactEmail.as_view(), name="send_contact_email"),
]
