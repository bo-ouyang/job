from starlette_admin.contrib.sqla import ModelView
from common.databases.models.user import UserRole
from ..utils import AuditMixin

class AdminRestrictedView(AuditMixin, ModelView):
    def is_accessible(self, request):
        user_role = getattr(request.state, "user_role", None)
        return user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]

class OperationsRestrictedView(AuditMixin, ModelView):
    def is_accessible(self, request):
        user_role = getattr(request.state, "user_role", None)
        return user_role in [UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.OPERATIONS]

    def can_delete(self, request):
        user_role = getattr(request.state, "user_role", None)
        # Operations cannot delete data
        if user_role == UserRole.OPERATIONS:
            return False
        return True
