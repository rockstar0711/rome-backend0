# api/permissions.py
from rest_framework import permissions

class IsStaffOrReviewer(permissions.BasePermission):
    """
    Custom permission to allow only staff or reviewers to perform actions.
    """

    def has_permission(self, request, view):
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # Check if user is staff or reviewer
        return request.user.is_staff or request.user.is_reviewer or request.user.is_superuser


class IsStaffOrReviewerOrReadOnly(permissions.BasePermission):
    """
    Allow read (GET) operations for all authenticated users,
    but restrict write (POST, PUT, PATCH, DELETE) to staff or reviewers only.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            # GET, HEAD, OPTIONS requests are allowed for any authenticated user
            return request.user.is_authenticated
        else:
            # Write permissions only for staff or reviewer
            return request.user.is_staff or request.user.is_reviewer or request.user.is_superuser

class IsStaffOrSuperAdmin(permissions.BasePermission):
    """
    Allow access only to staff users or super admins.
    """
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and
            user.is_authenticated and
            (user.is_staff or getattr(user, "is_super_admin", False))
        )