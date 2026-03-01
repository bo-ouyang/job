from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Enum, JSON, ForeignKey, BigInteger
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .base import Base
import enum
from common.utils.snowflake import generate_id

class UserRole(str, enum.Enum):
    """用户角色枚举"""
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    OPERATIONS = "operations"

class UserStatus(str, enum.Enum):
    """用户状态枚举"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"

class UserWechat(Base):
    """微信用户信息表"""
    __tablename__ = 'user_wechats'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), unique=True, nullable=False)
    
    openid = Column(String(100), unique=True, index=True, nullable=False)
    unionid = Column(String(100), unique=True, index=True, nullable=True, default='')
    nickname = Column(String(100), nullable=True, default='')
    avatar = Column(String(255), nullable=True, default='')
    session_key = Column(String(255), nullable=True, default='') # For mini-program
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationship
    user = relationship("User", back_populates="wechat_info")

class User(Base):
    """用户表"""
    __tablename__ = 'users'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    
    # 基础信息
    username = Column(String(50), unique=True, index=True, nullable=True)
    email = Column(String(100), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    
    # 微信相关 (已迁移至 UserWechat)
    # wx_openid = Column(String(100), unique=True, index=True, nullable=True)
    # wx_unionid = Column(String(100), unique=True, index=True, nullable=True)
    # wx_nickname = Column(String(100), nullable=True)
    # wx_avatar = Column(String(255), nullable=True)
    
    # 密码和安全
    hashed_password = Column(String(255), nullable=True)
    salt = Column(String(50), nullable=True)
    
    # 用户资料
    nickname = Column(String(50), default='')
    avatar = Column(String(255), default='')
    bio = Column(Text, default='')
    location = Column(String(100), default='')
    
    # 状态和角色
    role = Column(Enum(UserRole), default=UserRole.USER)
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE)
    is_verified = Column(Boolean, default=False)
    
    # 时间戳
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime, nullable=True)
    
    # 关系
    #user_query = relationship("UserQuery", back_populates="user")
    #user_session = relationship('UserSession',back_populates='user')
    resume = relationship("Resume", back_populates="user", uselist=False, lazy="selectin")
    
    # 支付订单关联
    payment_orders = relationship("PaymentOrder", back_populates="user", cascade="all, delete-orphan")
    
    # 钱包关联
    wallet = relationship("UserWallet", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    # 微信信息关联
    wechat_info = relationship("UserWechat", back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="joined")

    @property
    def wx_openid(self):
        return self.wechat_info.openid if self.wechat_info else None

    @property
    def wx_unionid(self):
        return self.wechat_info.unionid if self.wechat_info else None
        
    @property
    def wx_nickname(self):
        return self.wechat_info.nickname if self.wechat_info else None
        
    @property
    def wx_avatar(self):
        return self.wechat_info.avatar if self.wechat_info else None


    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}')>"

class VerificationCode(Base):
    """验证码表（用于手机验证）"""
    __tablename__ = 'verification_codes'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    phone = Column(String(20), nullable=False, index=True)
    code = Column(String(10), nullable=False)
    code_type = Column(String(20), nullable=False)  # login, register, reset_password
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f"<VerificationCode(id={self.id}, phone='{self.phone}')>"

class UserSession(Base):
    """用户会话表"""
    __tablename__ = 'user_sessions'
    
    id = Column(BigInteger, primary_key=True, default=generate_id, index=True)
    user_id = Column(BigInteger, index=True, nullable=True) # 移除 unique=True，类型改为 Integer
    session_token = Column(String(255), unique=True, index=True)
    device_info = Column(JSON, default={})  # 设备信息
    ip_address = Column(String(45), default='')
    user_agent = Column(Text, default='')
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    last_activity_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f"<UserSession(id={self.id}, user_id={self.user_id})>"
