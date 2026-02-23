import jwt
from datetime import datetime, timedelta
from typing import Any, Union, Optional
from passlib.context import CryptContext
from jwt import PyJWTError
import secrets
import hashlib
import hmac

from jobCollectionWebApi.config import settings
from common.databases.RedisManager import redis_manager

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_access_token(
    subject: Union[str, Any], 
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[dict] = None
) -> str:
    """创建访问令牌"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": datetime.utcnow(),
        "type": "access"
    }
    
    if additional_claims:
        to_encode.update(additional_claims)
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def create_refresh_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """创建刷新令牌"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": datetime.utcnow(),
        "type": "refresh"
    }
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[dict]:
    """验证令牌"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except PyJWTError:
        return None

async def blacklist_token(token: str, expires_in: int = None) -> bool:
    """将令牌加入黑名单"""
    if expires_in is None:
        # 如果未指定过期时间，尝试解析 token 获取其剩余有效期
        payload = verify_token(token)
        if payload and "exp" in payload:
            exp = payload["exp"]
            expires_in = int(exp - datetime.utcnow().timestamp())
        
    if expires_in and expires_in > 0:
        key = f"token_blacklist:{token}"
        return await redis_manager.set_cache(key, "1", expire=expires_in)
    return False

async def is_token_blacklisted(token: str) -> bool:
    """检查令牌是否在黑名单中"""
    key = f"token_blacklist:{token}"
    return await redis_manager.exists(key)

def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)

def generate_verification_code(length: int = 6) -> str:
    """生成验证码"""
    return ''.join(secrets.choice('0123456789') for _ in range(length))

def generate_random_string(length: int = 32) -> str:
    """生成随机字符串"""
    return secrets.token_urlsafe(length)

def create_hmac_signature(data: str, key: str) -> str:
    """创建 HMAC 签名"""
    return hmac.new(
        key.encode('utf-8'),
        data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def verify_hmac_signature(data: str, signature: str, key: str) -> bool:
    """验证 HMAC 签名"""
    expected_signature = create_hmac_signature(data, key)
    return hmac.compare_digest(expected_signature, signature)

def generate_session_token() -> str:
    """生成会话令牌"""
    return secrets.token_urlsafe(64)
