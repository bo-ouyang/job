from pydantic import BaseModel, EmailStr, ConfigDict,field_validator
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
import re

from .base_schema import TimestampSchema
from pydantic import field_serializer
from common.utils.masking import mask_email, mask_phone

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"
    OPERATIONS = "operations"

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"

# 基础模式
class UserBase(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None

# 创建模式
class UserCreate(UserBase):
    password: Optional[str] = None
    wx_openid: Optional[str] = None
    wx_unionid: Optional[str] = None
    
    @field_validator('password')
    def validate_password(cls, v):
        if v is not None:
            if len(v) < 6:
                raise ValueError('密码长度至少6位')
        return v
    
    @field_validator('phone')
    def validate_phone(cls, v):
        if v is not None:
            if not re.match(r'^1[3-9]\d{9}$', v):
                raise ValueError('手机号格式不正确')
        return v

# 更新模式
class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    password: Optional[str] = None

# 管理员更新模式
class UserAdminUpdate(UserUpdate):
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None

# 响应模式
class UserInDB(UserBase, TimestampSchema):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    is_verified: bool = False
    last_login_at: Optional[datetime] = None
    
    @field_serializer('email')
    def serialize_email(self, email: Optional[str], _info):
        return mask_email(email)

    @field_serializer('phone')
    def serialize_phone(self, phone: Optional[str], _info):
        return mask_phone(phone)

# 公开用户信息（不包含敏感信息）
class UserPublic(UserInDB):
    pass

# 详细用户信息（包含微信信息）
class UserDetail(UserInDB):
    wx_nickname: Optional[str] = None
    wx_avatar: Optional[str] = None

# 用户统计信息
class UserStats(BaseModel):
    total_queries: int = 0
    favorite_jobs: int = 0
    saved_searches: int = 0

# 用户列表响应
class UserList(BaseModel):
    items: list[UserPublic]
    total: int
    page: int
    size: int
    pages: int
