from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from common.databases.models.user import User, VerificationCode, UserSession, UserRole, UserStatus, UserWechat
from jobCollectionWebApi.schemas.user_schema import UserCreate, UserUpdate
from .wallet import wallet as crud_wallet
from .base import CRUDBase
from jobCollectionWebApi.core.security import get_password_hash, verify_password, generate_session_token
from datetime import datetime, timedelta

class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    """用户 CRUD 操作"""
    
    async def get_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_phone(self, db: AsyncSession, phone: str) -> Optional[User]:
        """根据手机号获取用户"""
        stmt = select(User).where(User.phone == phone)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_wx_openid(self, db: AsyncSession, wx_openid: str) -> Optional[User]:
        """根据微信openid获取用户"""
        # Join query to find user by wechat info
        stmt = select(User).join(UserWechat).where(UserWechat.openid == wx_openid)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_wx_unionid(self, db: AsyncSession, wx_unionid: str) -> Optional[User]:
        """根据微信unionid获取用户"""
        stmt = select(User).join(UserWechat).where(UserWechat.unionid == wx_unionid)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(self, db: AsyncSession, *, obj_in: UserCreate) -> User:
        """创建用户"""
        # 处理密码
        hashed_password = None
        if obj_in.password:
            hashed_password = get_password_hash(obj_in.password)
        
        # 创建用户对象
        db_obj = User(
            username=obj_in.username,
            email=obj_in.email,
            phone=obj_in.phone,
            nickname=obj_in.nickname,
            avatar=obj_in.avatar,
            hashed_password=hashed_password,
        )
        
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        
        # Handle Wechat Info if present in obj_in
        if obj_in.wx_openid:
            db_wechat = UserWechat(
                user_id=db_obj.id,
                openid=obj_in.wx_openid,
                unionid=obj_in.wx_unionid
            )
            db.add(db_wechat)
            await db.flush()

        # 注册成功后初始化钱包，默认赠送 10
        await crud_wallet.create_wallet(db, user_id=db_obj.id, initial_balance=10.0)

        return db_obj
    
    async def create_with_wechat(self, db: AsyncSession, wechat_info: dict) -> User:
        """使用微信信息创建用户"""
        # 1. Create User
        db_user = User(
            nickname=wechat_info.get("nickname"),
            avatar=wechat_info.get("avatar"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE
        )
        db.add(db_user)
        await db.flush() # Get ID
        
        # 2. Create UserWechat
        db_wechat = UserWechat(
            user_id=db_user.id,
            openid=wechat_info.get("openid"),
            unionid=wechat_info.get("unionid"),
            nickname=wechat_info.get("nickname"),
            avatar=wechat_info.get("avatar")
        )
        db.add(db_wechat)

        # 微信注册用户同样初始化钱包，默认赠送 10
        await crud_wallet.create_wallet(db, user_id=db_user.id, initial_balance=10.0)

        await db.flush()
        await db.refresh(db_user)
        return db_user
    
    async def authenticate(self, db: AsyncSession, username: str, password: str) -> Optional[User]:
        """用户名密码认证"""
        user = await self.get_by_username(db, username=username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user
    
    async def update_last_login(self, db: AsyncSession, user_id: int) -> None:
        """更新最后登录时间"""
        user = await self.get(db, id=user_id)
        if user:
            user.last_login_at = datetime.now()
            db.add(user)
            await db.flush()
    
    async def search(
        self, 
        db: AsyncSession, 
        *, 
        keyword: Optional[str] = None,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
        skip: int = 0, 
        limit: int = 50
    ) -> List[User]:
        """搜索用户"""
        stmt = select(User)
        
        conditions = []
        if keyword:
            conditions.append(
                or_(
                    User.username.contains(keyword),
                    User.nickname.contains(keyword),
                    User.email.contains(keyword)
                )
            )
        
        if role:
            conditions.append(User.role == role)
        
        if status:
            conditions.append(User.status == status)
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

user = CRUDUser(User)

class CRUDVerificationCode(CRUDBase[VerificationCode, VerificationCode, VerificationCode]):
    """验证码 CRUD 操作"""
    
    async def create_code(self, db: AsyncSession, phone: str, code: str, code_type: str) -> VerificationCode:
        """创建验证码"""
        expires_at = datetime.now() + timedelta(minutes=10)  # 10分钟有效期
        
        db_obj = VerificationCode(
            phone=phone,
            code=code,
            code_type=code_type,
            expires_at=expires_at
        )
        
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj
    
    async def get_valid_code(self, db: AsyncSession, phone: str, code: str, code_type: str) -> Optional[VerificationCode]:
        """获取有效的验证码"""
        stmt = select(VerificationCode).where(
            and_(
                VerificationCode.phone == phone,
                VerificationCode.code == code,
                VerificationCode.code_type == code_type,
                VerificationCode.expires_at > datetime.now(),
                VerificationCode.is_used == False
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def mark_used(self, db: AsyncSession, code_id: int) -> None:
        """标记验证码为已使用"""
        code = await self.get(db, id=code_id)
        if code:
            code.is_used = True
            db.add(code)
            await db.flush()

verification_code = CRUDVerificationCode(VerificationCode)

class CRUDUserSession(CRUDBase[UserSession, UserSession, UserSession]):
    """用户会话 CRUD 操作"""
    
    async def create_session(self, db: AsyncSession, user_id: int, device_info: dict = None, 
                           ip_address: str = None, user_agent: str = None) -> UserSession:
        """创建用户会话"""
        expires_at = datetime.now() + timedelta(days=30)  # 30天有效期
        
        db_obj = UserSession(
            user_id=user_id,
            session_token=generate_session_token(),
            device_info=device_info,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at
        )
        
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj
    
    async def get_by_token(self, db: AsyncSession, session_token: str) -> Optional[UserSession]:
        """根据会话令牌获取会话"""
        stmt = select(UserSession).where(
            and_(
                UserSession.session_token == session_token,
                UserSession.expires_at > datetime.now(),
                UserSession.is_active == True
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def deactivate_session(self, db: AsyncSession, session_token: str) -> None:
        """停用会话"""
        session = await self.get_by_token(db, session_token)
        if session:
            session.is_active = False
            db.add(session)
            await db.flush()

user_session = CRUDUserSession(UserSession)
