from fastapi import Depends, HTTPException, status, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from core.logger import sys_logger as logger
import time
from typing import AsyncGenerator, Optional
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings
from core.security import verify_token, is_token_blacklisted
from crud import user as crud_user
from schemas.token_schema import TokenData
from common.databases.PostgresManager import db_manager
from common.databases.RedisManager import get_redis, RedisManager

# 安全方案
security = HTTPBearer()

# 数据库依赖
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话依赖"""
    async for session in db_manager.get_db():
        try:
            # Auto-commit successful requests, rollback failed requests.
            # This prevents "flush without commit" data loss patterns.
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据xxxxx",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = credentials.credentials
    payload = verify_token(token)
    
    if payload is None or await is_token_blacklisted(token):
        raise credentials_exception
    
    user_id: int = int(payload.get("sub"))
    if user_id is None:
        raise credentials_exception
    
    user = await crud_user.get(db, id=user_id)
    if user is None:
        raise credentials_exception
    
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户账户已被禁用"
        )
    
    return user

async def get_current_admin_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取当前管理员用户"""
    if current_user.role not in ["admin", "super_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足"
        )
    return current_user

# 获取客户端信息
async def get_client_info(
    request: Request,
    user_agent: Optional[str] = Header(None),
    x_forwarded_for: Optional[str] = Header(None),
    x_real_ip: Optional[str] = Header(None),
) -> dict:
    """获取客户端信息"""
    client_ip = x_forwarded_for or x_real_ip or request.client.host
    
    return {
        "ip_address": client_ip,
        "user_agent": user_agent
    }

# 分页依赖
class PaginationParams:
    """分页参数依赖"""
    
    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码"),
        page_size: int = Query(20, ge=1, le=100, description="每页数量")
    ):
        self.page = page
        self.page_size = page_size
        self.skip = (page - 1) * page_size

# 搜索依赖
class SearchParams:
    """搜索参数依赖"""
    
    def __init__(
        self,
        q: Optional[str] = Query(None, max_length=100, description="搜索关键词"),
        sort: Optional[str] = Query(None, max_length=50, description="排序字段"),
        order: Optional[str] = Query("desc", pattern="^(asc|desc)$", description="排序方向")
    ):
        self.q = q
        self.sort = sort
        self.order = order

# 通用查询参数依赖
class CommonQueryParams:
    """通用查询参数依赖"""
    
    def __init__(
        self,
        pagination: PaginationParams = Depends(),
        search: SearchParams = Depends()
    ):
        self.pagination = pagination
        self.search = search

# 缓存键生成依赖
def get_cache_key(
    prefix: str,
    pagination: PaginationParams = Depends(),
    search: SearchParams = Depends(),
    **filters
) -> str:
    """
    生成缓存键的依赖
    """
    key_parts = [prefix]
    
    # 添加分页信息
    key_parts.append(f"page_{pagination.page}")
    key_parts.append(f"size_{pagination.page_size}")
    
    # 添加搜索信息
    if search.q:
        key_parts.append(f"q_{search.q}")
    if search.sort:
        key_parts.append(f"sort_{search.sort}")
    if search.order:
        key_parts.append(f"order_{search.order}")
    
    # 添加过滤条件
    for key, value in filters.items():
        if value is not None:
            key_parts.append(f"{key}_{value}")
    
    return ":".join(key_parts)

# 请求日志依赖
async def log_request(
    user_agent: Optional[str] = Header(None),
    x_forwarded_for: Optional[str] = Header(None),
    x_real_ip: Optional[str] = Header(None),
):
    """
    请求日志记录依赖
    """
    client_ip = x_forwarded_for or x_real_ip or "unknown"
    
    logger.info(f"Request from IP: {client_ip}, User-Agent: {user_agent}")
    
    return {
        "client_ip": client_ip,
        "user_agent": user_agent
    }

# 数据库健康检查依赖
async def verify_db_health():
    """
    数据库健康检查依赖
    在关键操作前验证数据库连接
    """
    is_healthy = await db_manager.health_check()
    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        )
    return True

# 速率限制依赖（基础版本）

class RateLimiter:
    """基于 Redis 的分布式速率限制器 (防穿透 & 无僵尸Key进阶版)"""
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        # 使用 Lua 保证 INCR 和 EXPIRE 是绝对原子绑定操作，永不产生僵尸Key
        self.lua_script = """
        local current = redis.call("INCR", KEYS[1])
        if current == 1 then
            redis.call("EXPIRE", KEYS[1], tonumber(ARGV[1]))
        end
        return current
        """
    
    async def __call__(
        self,
        client_info: dict = Depends(log_request),
        redis: RedisManager = Depends(get_redis)  # 注入 Redis
    ):
        from core.exceptions import AppException
        from core.status_code import StatusCode
        
        client_ip = client_info["client_ip"]
        current_minute = int(time.time()) // 60  # 按分钟分组
        # 构造限流计数器 key，注意这里用 redis manager 的 make_key 包装前缀
        limit_key = redis.make_key(f"rate_limit:{client_ip}:{current_minute}")
        
        try:
            # 1. 原子化执行计数+过期（60秒自动清理）
            current_count = await redis.redis_client.eval(
                self.lua_script, 1, limit_key, 60
            )
        except Exception as e:
            logger.error(f"Rate Limiter Redis Error: {e}")
            # 如果 Redis 宕机或者出错，选择降级放行还是拒绝？这里选择暂时放行保证业务可用性
            return
        
        # 2. 检查是否超限
        if current_count > self.requests_per_minute:
            raise AppException(
                status_code=429,
                code=StatusCode.TOO_MANY_REQUESTS,
                message=f"限流触发！每分钟最多 {self.requests_per_minute} 次请求"
            )
            

# 创建限流实例
rate_limiter = RateLimiter(requests_per_minute=60)
