import logging
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta

from core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token, 
    create_refresh_token,
    generate_verification_code
)
from crud import (
    user as crud_user, 
    verification_code as crud_verification_code,
    user_session as crud_user_session
)
from schemas.user import UserCreate, UserPublic, UserUpdate
from schemas.token import Token, LoginResponse, WechatLoginRequest, PhoneLoginRequest, LoginRequest
from config import settings
from services.wechat_service import wechat_service
import uuid
import json
from common.databases.RedisManager import redis_manager
from common.databases.models.user import User

logger = logging.getLogger(__name__)

class AuthService:
    """认证服务类"""
    
    def __init__(self):
        pass
    
    async def authenticate_user(
        self, 
        db: AsyncSession, 
        username: str, 
        password: str
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        用户名密码认证
        """
        try:
            # 同时支持用户名和邮箱登录
            user = await crud_user.get_by_username(db, username=username)
            if not user:
                user = await crud_user.get_by_email(db, email=username)
            
            if not user:
                logger.warning(f"Authentication failed: User {username} not found")
                return False, None

            if not user.hashed_password:
                logger.warning(f"Authentication failed: User {username} has no password set")
                return False, None
                
            if not verify_password(password, user.hashed_password):
                logger.warning(f"Authentication failed: Password mismatch for user {username}")
                # Debug logging - Remove in production
                # logger.info(f"Input: {password}, Hash: {user.hashed_password}")
                return False, None
            
            if user.status != "active":
                logger.warning(f"Authentication failed: User {username} is inactive")
                return False, {"error": "账户已被禁用"}
            
            return True, user
            
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False, {"error": "认证过程发生错误"}

    async def login_with_password(
        self,
        db: AsyncSession,
        request: LoginRequest,
        client_info: dict = None
    ) -> LoginResponse:
        """用户名/邮箱 + 密码登录"""
        success, result = await self.authenticate_user(db, request.username, request.password)
        #print(success, result)

        if not success:
            raise ValueError(result.get("error") if result else "用户名或密码错误")
        
        user = result
        response = await self.create_login_response(db, user.id)
        #print(response)
        # 创建会话记录
        if client_info:
            await crud_user_session.create_session(
                db, 
                user.id, 
                ip_address=client_info.get("ip_address"),
                user_agent=client_info.get("user_agent")
            )
            
        return response
    
    async def register_user(
        self, 
        db: AsyncSession, 
        user_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        注册新用户
        """
        try:
            if user_data.get("username"):
                existing_user = await crud_user.get_by_username(db, user_data["username"])
                if existing_user:
                    return False, None, "用户名已存在"
            
            if user_data.get("email"):
                existing_user = await crud_user.get_by_email(db, user_data["email"])
                if existing_user:
                    return False, None, "邮箱已被注册"

            if user_data.get("phone"):
                existing_user = await crud_user.get_by_phone(db, user_data["phone"])
                if existing_user:
                    return False, None, "手机号已被注册"
            
            user_create = UserCreate(**user_data)
            user = await crud_user.create(db, obj_in=user_create)
            
            response = await self.create_login_response(db, user.id, is_new_user=True)
            return True, response.model_dump(), None
            
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False, None, f"注册失败: {str(e)}"
    
    async def create_tokens(self, user_id: int, username: str, role: str) -> Token:
        """
        为用户创建访问令牌和刷新令牌
        """
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            subject=user_id,
            expires_delta=access_token_expires,
            additional_claims={"username": username, "role": role}
        )
        
        refresh_token = create_refresh_token(subject=user_id)
        
        return Token(
            access_token=access_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            refresh_token=refresh_token
        )
    
    async def create_login_response(
        self, 
        db: AsyncSession, 
        user_id: int, 
        is_new_user: bool = False
    ) -> LoginResponse:
        """
        创建登录响应
        """
        user = await crud_user.get(db, id=user_id)
        if not user:
            raise ValueError("用户不存在")
        
        # 更新最后登录时间
        await crud_user.update_last_login(db, user.id)
        
        token = await self.create_tokens(user.id, user.username or "", user.role)
        
        # 修复: 在序列化前刷新对象，确保 updated_at 等所有属性已加载 (避免 MissingGreenlet 错误)
        await db.refresh(user)
        
        user_public = UserPublic.model_validate(user)
        
        return LoginResponse(
            token=token,
            user=user_public.model_dump(),
            is_new_user=is_new_user
        )
    
    async def verify_phone_code(
        self, 
        db: AsyncSession, 
        phone: str, 
        code: str, 
        code_type: str = "login"
    ) -> Tuple[bool, Optional[str]]:
        """
        验证手机验证码
        """
        try:
            verification_code = await crud_verification_code.get_valid_code(
                db, phone, code, code_type
            )
            
            if not verification_code:
                return False, "验证码无效或已过期"
            
            await crud_verification_code.mark_used(db, verification_code.id)
            return True, None
            
        except Exception as e:
            logger.error(f"Phone code verification error: {e}")
            return False, "验证过程发生错误"
    
    async def send_phone_verification_code(
        self, 
        db: AsyncSession, 
        phone: str, 
        code_type: str = "login"
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        发送手机验证码
        """
        try:
            code = generate_verification_code()
            
            await crud_verification_code.create_code(
                db, phone, code, code_type
            )
            
            if settings.DEBUG:
                logger.info(f"Verification code for {phone}: {code}")
                return True, code, None
            else:
                logger.info(f"Verification code sent to {phone}")
                return True, None, None
            
        except Exception as e:
            logger.error(f"Send verification code error: {e}")
            return False, None, "发送验证码失败"

    async def login_with_wechat(
        self,
        db: AsyncSession,
        code: str,
        client_info: dict = None
    ) -> LoginResponse:
        """微信登录逻辑"""
        wechat_info = await wechat_service.login_with_code(code)
        if not wechat_info or not wechat_info.get("openid"):
            raise ValueError("微信登录失败或获取用户信息失败")

        openid = wechat_info.get("openid")
        user = await crud_user.get_by_wx_openid(db, wx_openid=openid)
        is_new_user = False

        if not user:
            user = await crud_user.create_with_wechat(db, wechat_info)
            is_new_user = True

        response = await self.create_login_response(db, user.id, is_new_user=is_new_user)
        
        # 创建会话记录
        if client_info:
            await crud_user_session.create_session(
                db, 
                user.id, 
                ip_address=client_info.get("ip_address"),
                user_agent=client_info.get("user_agent")
            )
            
        return response

    async def login_with_phone(
        self,
        db: AsyncSession,
        phone: str,
        code: str,
        client_info: dict = None
    ) -> LoginResponse:
        """手机号登录逻辑"""
        success, error = await self.verify_phone_code(db, phone, code, "login")
        if not success:
            raise ValueError(error)

        user = await crud_user.get_by_phone(db, phone=phone)
        is_new_user = False

        if not user:
            user_in = UserCreate(phone=phone)
            user = await crud_user.create(db, obj_in=user_in)
            is_new_user = True

        response = await self.create_login_response(db, user.id, is_new_user=is_new_user)
        
        # 创建会话记录
        if client_info:
            await crud_user_session.create_session(
                db, 
                user.id, 
                ip_address=client_info.get("ip_address"),
                user_agent=client_info.get("user_agent")
            )
            
        return response

    async def refresh_access_token(
        self,
        db: AsyncSession,
        refresh_token: str
    ) -> Token:
        """刷新访问令牌"""
        from core.security import verify_token
        payload = verify_token(refresh_token)

        if not payload or payload.get("type") != "refresh":
            raise ValueError("刷新令牌无效")

        user_id = int(payload.get("sub"))
        user = await crud_user.get(db, id=user_id)

        if not user or user.status != "active":
            raise ValueError("用户不存在或已被禁用")

        # Create new access token
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        new_access_token = create_access_token(
            subject=user.id,
            expires_delta=access_token_expires,
            additional_claims={"username": user.username, "role": user.role}
        )
        
        # Optionally rotate refresh token here if needed, but for now just new access token
        # Return Token model
        return Token(
            access_token=new_access_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            refresh_token=refresh_token # Return original refresh token or rotate
        )

    async def create_qrcode_ticket(self) -> str:
        """生成二维码 Ticket"""
        ticket = str(uuid.uuid4())
        data = {
            "status": "waiting",
            "created_at": datetime.now().isoformat()
        }
        await redis_manager.set_cache(f"qrcode:{ticket}", data, expire=300) # 5分钟有效期
        return ticket

    async def get_qrcode_status(self, ticket: str) -> Dict[str, Any]:
        """查询二维码状态"""
        data = await redis_manager.get_cache(f"qrcode:{ticket}")
        if not data:
            return {"status": "expired"}
        return data

    async def qrcode_scan(self, ticket: str, user_id: int) -> bool:
        """
        APP端扫码操作
        :param ticket: 二维码凭证
        :param user_id: 扫码用户的ID
        """
        key = f"qrcode:{ticket}"
        data = await redis_manager.get_cache(key)
        if not data:
            return False
            
        if data.get("status") != "waiting":
            return False
            
        data["status"] = "scanned"
        data["scanned_by"] = user_id
        await redis_manager.set_cache(key, data, expire=300)
        return True

    async def qrcode_confirm(self, db: AsyncSession, ticket: str, user_id: int) -> bool:
        """
        APP端确认登录操作
        :param ticket: 二维码凭证
        :param user_id: 确认用户的ID
        """
        key = f"qrcode:{ticket}"
        data = await redis_manager.get_cache(key)
        
        # 验证 Ticket 有效性及状态
        if not data or data.get("status") != "scanned":
            return False
            
        # 验证是否是同一个人扫码 (可选，但推荐)
        if data.get("scanned_by") != user_id:
            return False

        # 生成 Web 端可用的 Token (为该用户生成新的登录凭证)
        response = await self.create_login_response(db, user_id, is_new_user=False)
        
        data["status"] = "confirmed"
        data["login_data"] = response.model_dump()
        
        await redis_manager.set_cache(key, data, expire=60)
        return True

    # --- Deprecated / Dev Methods below ---
    async def simulate_qrcode_scan(self, ticket: str) -> bool:
        """模拟扫码"""
        key = f"qrcode:{ticket}"
        data = await redis_manager.get_cache(key)
        if not data:
            return False
        
        data["status"] = "scanned"
        await redis_manager.set_cache(key, data, expire=300)
        return True

    async def simulate_qrcode_confirm(self, db: AsyncSession, ticket: str, user_id: int = None) -> bool:
        """模拟确认登录"""
        key = f"qrcode:{ticket}"
        data = await redis_manager.get_cache(key)
        if not data:
            return False
        
        # 如果没有指定用户，找一个默认用户或者随机用户
        if not user_id:
            # For demo: use the first user
            stmt = select(crud_user.model).limit(1)
            result = await db.execute(stmt)
            user = result.scalars().first()
            if not user:
                 # Create a demo user if none exists
                 user_in = UserCreate(username="demo_user", password="password", phone="13800000000")
                 user = await crud_user.create(db, obj_in=user_in)
        else:
            user = await crud_user.get(db, id=user_id)
            
        if not user:
            return False

        # 生成 Token
        response = await self.create_login_response(db, user.id, is_new_user=False)
        
        data["status"] = "confirmed"
        data["login_data"] = response.model_dump()
        
        # Update Redis, verify token logic needs to access this
        # Note: LoginResponse contains `token` object which might need JSON serialization handling if not dict
        # response.model_dump() handles it.
        
        await redis_manager.set_cache(key, data, expire=60) # 确认后很快就会被取走，无需久存
        return True

    async def get_user_from_token_str(self, token_str: str) -> Optional[User]:
        """
        根据 Token 字符串解析并获取用户（用于 WebSocket）
        """
        try:
            from core.security import verify_token
            payload = verify_token(token_str)
            if not payload:
                return None
            
            user_id = int(payload.get("sub"))
            
            # Use a fresh session ideally, or use the global manager and handle it.
            # Since this is likely called inside an endpoint where db_manager is available.
            # But inside WS, we need to manage sessions.
            # Simple approach: Create a temporary session.
            from common.databases.PostgresManager import db_manager
            async with db_manager.async_session() as session:
                 user = await crud_user.get(session, id=user_id)
                 return user
        except Exception as e:
            logger.error(f"Error getting user from token: {e}")
            return None

# 全局认证服务实例
auth_service = AuthService()
