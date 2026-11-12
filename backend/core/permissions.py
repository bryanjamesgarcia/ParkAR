from rest_framework.permissions import BasePermission
from .serializers import role_of

class HasRole(BasePermission):
    allowed_roles = set()
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and role_of(request.user) in self.allowed_roles)

class IsProvider(HasRole):
    allowed_roles = {"provider", "admin"}

class IsAdministrator(HasRole):
    allowed_roles = {"admin"}

