from starlette_admin import row_action
from common.databases.PostgresManager import db_manager
from common.databases.models.user import User, UserStatus
from .base import AdminRestrictedView

class UserView(AdminRestrictedView):
    fields = [User.id, User.username, User.email, User.phone, User.role, User.status, User.created_at]
    exclude_fields_from_list = [User.hashed_password]
    exclude_fields_from_detail = [User.hashed_password]
    exclude_fields_from_create = [User.created_at, User.updated_at, User.last_login_at]
    exclude_fields_from_edit = [User.created_at, User.updated_at, User.last_login_at]
    search_builder = True

    @row_action(
        name="ban_user",
        text="封禁",
        confirmation="确定要封禁该用户吗？",
        icon_class="fas fa-ban",
        action_btn_class="btn-danger",
        submit_btn_text="确认封禁",
        submit_btn_class="btn-danger",
    )
    async def ban_user(self, request, pk):
        async with db_manager.async_session() as session:
            obj = await session.get(User, int(pk))
            if obj:
                username = obj.username  # Capture before commit
                obj.status = UserStatus.BANNED
                session.add(obj)
                await session.commit()
                await self._log_action(request, "BAN", obj, f"Banned user {username}")
        return "用户已封禁"

    @row_action(
        name="unban_user",
        text="解封",
        confirmation="确定要解封该用户吗？",
        icon_class="fas fa-check-circle",
        action_btn_class="btn-success",
        submit_btn_text="确认解封",
        submit_btn_class="btn-success",
    )
    async def unban_user(self, request, pk):
        async with db_manager.async_session() as session:
            obj = await session.get(User, int(pk))
            if obj:
                username = obj.username # Capture before commit
                obj.status = UserStatus.ACTIVE
                session.add(obj)
                await session.commit()
                await self._log_action(request, "UNBAN", obj, f"Unbanned user {username}")
        return "用户已解封"

    async def before_create(self, request, data, obj):
        # Handle password hashing
        if obj.hashed_password:
            from core.security import get_password_hash
            obj.hashed_password = get_password_hash(obj.hashed_password)
        
        # Handle unique fields - convert empty strings to None
        if obj.email == "":
            obj.email = None
        if obj.phone == "":
            obj.phone = None

    async def before_edit(self, request, data, obj, original_obj):
        # Handle password hashing if it's being updated
        if obj.hashed_password:
             from core.security import get_password_hash
             if obj.hashed_password != original_obj.hashed_password:
                 obj.hashed_password = get_password_hash(obj.hashed_password)
        else:
             # If empty, keep original password
             obj.hashed_password = original_obj.hashed_password

        # Handle unique fields
        if obj.email == "":
            obj.email = None
        if obj.phone == "":
            obj.phone = None
