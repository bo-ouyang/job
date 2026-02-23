from starlette_admin.auth import AuthProvider
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from services.auth_service import auth_service
from core.security import verify_token, create_access_token
from common.databases.PostgresManager import db_manager
from schemas.token import LoginRequest
from common.databases.models.user import UserRole

class AdminAuth(AuthProvider):
    async def login(self, username, password, remember_me, request: Request, response: Response) -> Response:
        # Use a new db session for login check
        async with db_manager.async_session() as session:
            try:
                # Reuse existing login logic which verifies password
                login_req = LoginRequest(username=username, password=password)
                #print(login_req)
                result = await auth_service.login_with_password(session, login_req, client_info={"ip": request.client.host})
                #print(result)
                # If successful, we get token.
                token = result.token.access_token
                # Use the provided response (which is a RedirectResponse from render_login)
                # Or create a new one if we want to force specific behavior
                # But treating the passed response is better.
                response.set_cookie("access_token", token, httponly=True, max_age=86400)
                return response
            except Exception as e:
                print(f"❌ Admin Login Exception: {e}")
                import traceback
                traceback.print_exc()
                # If login fails, we should probably raise LoginFailed to show error on form
                from starlette_admin.exceptions import LoginFailed
                raise LoginFailed("用户名或密码错误")

    async def is_authenticated(self, request: Request) -> bool:
        token = request.cookies.get("access_token")
        if not token:
            return False
        
        # Verify token format
        payload = verify_token(token)
        if not payload:
            return False
            
        # Verify user role in DB
        user_id = payload.get("sub")
        if not user_id:
            return False
            
        async with db_manager.async_session() as session:
            from common.databases.models.user import User
            from sqlalchemy import select
            
            stmt = select(User).where(User.id == int(user_id))
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                return False
                
            # Check Role
            if user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN, UserRole.OPERATIONS]:
                return False
                
            request.state.user = payload 
            request.state.user_role = user.role
            request.state.user_obj = user # Optional, for get_admin_user
            return True

    async def get_admin_user(self, request: Request):
        from starlette_admin import AdminUser
        user = getattr(request.state, "user_obj", None)
        if user:
             return AdminUser(username=user.username, photo_url=user.avatar)
        return None

    async def logout(self, request: Request, response: Response) -> Response:
        response.delete_cookie("access_token")
        return response
