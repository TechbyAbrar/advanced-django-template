#authentication/permissions.py
from rest_framework import permissions

class IsAuthorOrSuperuser(permissions.BasePermission):
    """
    Read allowed to everyone.
    Write allowed to the object's author or a superuser.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        user = request.user
        return (
            bool(user and user.is_authenticated) and
            (obj.author_id == user.id or user.is_superuser)
        )


class IsSuperuserOrReadOnly(permissions.BasePermission):
    """
    Read allowed to everyone.
    Write allowed only to superusers.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


class IsSelfOrAdmin(permissions.BasePermission):
    """
    Access allowed to the object owner, staff, or superuser.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_staff or user.is_superuser:
            return True

        return obj.pk == user.pk