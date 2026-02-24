from common.databases.models.admin_log import AdminLog
from common.databases.PostgresManager import db_manager

class AuditMixin:
    """Mixin to log Create, Edit, Delete actions in Admin Panel"""

    async def _log_action(self, request, action, obj, details=None):
        user = getattr(request.state, "user_obj", None)
        user_id = user.id if user else None
        username = user.username if user else "Unknown"
        ip = request.client.host if request.client else None
        
        try:
            async with db_manager.async_session() as session:
                log = AdminLog(
                    user_id=user_id,
                    username=username,
                    action=action,
                    model_name=self.model.__tablename__,
                    object_id=str(obj.id) if hasattr(obj, "id") else "Unknown",
                    details=details,
                    ip_address=ip
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            print(f"❌ Failed to write admin log: {e}")

    async def after_create(self, request, obj):
        await super().after_create(request, obj)
        await self._log_action(request, "CREATE", obj, f"Created {obj}")

    async def after_edit(self, request, obj):
        await super().after_edit(request, obj)
        await self._log_action(request, "EDIT", obj, f"Edited object {obj}")

    async def after_delete(self, request, obj):
        await super().after_delete(request, obj)
        await self._log_action(request, "DELETE", obj, f"Deleted {obj}")
