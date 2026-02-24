from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

class Token(BaseModel):
    """令牌响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None

class TokenPayload(BaseModel):
    """令牌载荷"""
    sub: int  # 用户ID
    username: Optional[str] = None
    role: str = "user"
    exp: int

class TokenData(BaseModel):
    """令牌数据"""
    user_id: Optional[int] = None
    username: Optional[str] = None
    role: Optional[str] = None

class WechatLoginRequest(BaseModel):
    """微信登录请求"""
    code: str

class PhoneLoginRequest(BaseModel):
    """手机登录请求"""
    phone: str
    verification_code: str

class LoginRequest(BaseModel):
    """密码登录请求"""
    username: str  # 可以是用户名或邮箱
    password: str

class SendSMSRequest(BaseModel):
    """发送短信请求"""
    phone: str
    type: str = "login"  # login, register, reset_password

class RefreshTokenRequest(BaseModel):
    """刷新令牌请求"""
    refresh_token: str

class LoginResponse(BaseModel):
    """登录响应"""
    token: Token
    user: dict
    is_new_user: bool = False
