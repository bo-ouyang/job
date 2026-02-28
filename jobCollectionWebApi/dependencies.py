from fastapi import Depends, HTTPException, status, Header, Query,Request
from sqlalchemy.ext.asyncio import AsyncSession
from core.logger import sys_logger as logger
import time
from typing import AsyncGenerator, Optional
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from core.logger import sys_logger as logger
from config import settings
from core.security import verify_token, is_token_blacklisted
from crud import user as crud_user
from schemas.token import TokenData
from common.databases.PostgresManager import db_manager
from common.databases.RedisManager import get_redis,RedisManager
from fastapi import Depends, HTTPException, status, Request
# 安全方案
security = HTTPBearer()

# 数据库依赖
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库会话依赖"""
    async for session in db_manager.get_db():
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()

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

async def get_current_active_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取当前活跃用户"""
    if current_user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="用户账户已被禁用"
        )
    return current_user

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

async def get_current_super_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """获取当前超级管理员"""
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要超级管理员权限"
        )
    return current_user

# 可选的用户认证（不强制要求登录）
async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[dict]:
    """获取可选用户（如果提供了有效的令牌）"""
    authorization = request.headers.get("Authorization")
    
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)
    
    if payload is None or await is_token_blacklisted(token):
        return None
    
    user_id: int = int(payload.get("sub"))
    if user_id is None:
        return None
    
    user = await crud_user.get(db, id=user_id)
    if user is None or user.status != "active":
        return None
    
    return user

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
        q: Optional[str] = Query(None, description="搜索关键词"),
        sort: Optional[str] = Query(None, description="排序字段"),
        order: Optional[str] = Query("desc", regex="^(asc|desc)$", description="排序方向")
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

# 认证依赖（基础版本）
async def get_api_key(
    x_api_key: Optional[str] = Header(None, description="API Key")
) -> str:
    """
    API Key 认证依赖
    使用示例:
        async def protected_endpoint(api_key: str = Depends(get_api_key)):
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key is missing"
        )
    
    # 这里可以添加更复杂的认证逻辑
    # 例如验证 API Key 是否有效、检查权限等
    valid_api_keys = settings.API_KEYS
    if valid_api_keys and x_api_key not in valid_api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    
    return x_api_key



# 管理员权限依赖
async def get_admin_user(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    管理员权限验证依赖
    """
    role = getattr(current_user, "role", None)
    if role not in ["admin", "super_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )
    return current_user

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
    """基于 Redis 的分布式速率限制器"""
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
    
    async def __call__(
        self,
        client_info: dict = Depends(log_request),
        redis: RedisManager = Depends(get_redis)  # 注入 Redis
    ):
        client_ip = client_info["client_ip"]
        current_minute = int(time.time()) // 60  # 按分钟分组
        # 构造限流计数器 key
        limit_key = f"rate_limit:{client_ip}:{current_minute}"
        
        # 1. 自增计数器
        
        current_count = await redis.increment_counter(limit_key)
        
        # 2. 第一次计数时，设置过期时间（60秒，自动清理）
        if current_count == 1:
            await redis.redis_client.expire(redis.make_key(limit_key), 60)
        
        # 3. 检查是否超限
        if current_count > self.requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"限流触发！每分钟最多 {self.requests_per_minute} 次请求"
            )
            

# 创建限流实例
rate_limiter = RateLimiter(requests_per_minute=60)

# 作业查询特定依赖
class JobQueryParams:
    """职位查询特定参数依赖"""
    
    def __init__(
        self,
        location: Optional[int] = Query(None, description="工作地点"),
        experience: Optional[str] = Query(None, description="经验要求"),
        education: Optional[str] = Query(None, description="学历要求"),
        work_type: Optional[str] = Query(None, description="工作类型"),
        salary_min: Optional[float] = Query(None, ge=0, description="最低薪资"),
        salary_max: Optional[float] = Query(None, ge=0, description="最高薪资"),
        
        company_id: Optional[int] = Query(None, description="公司ID"),
        industry: Optional[int] = Query(None, description="行业"),
        industry_2: Optional[int] = Query(None, description="二级行业"),
        common: CommonQueryParams = Depends()
    ):
        self.location = location
        self.experience = experience
        self.education = education
        self.work_type = work_type
        self.salary_min = salary_min
        self.salary_max = salary_max
        self.company_id = company_id
        self.industry = industry
        self.industry_2 = industry_2
        self.common = common

# 技能查询特定依赖
class SkillQueryParams:
    """技能查询特定参数依赖"""
    
    def __init__(
        self,
        category: Optional[str] = Query(None, description="技能分类"),
        common: CommonQueryParams = Depends()
    ):
        self.category = category
        self.common = common

# 分析查询特定依赖
class AnalysisQueryParams:
    """分析查询特定参数依赖"""
    
    def __init__(
        self,
        analysis_type: Optional[str] = Query(None, description="分析类型"),
        days: Optional[int] = Query(7, ge=1, le=365, description="时间范围（天）"),
        common: CommonQueryParams = Depends()
    ):
        self.analysis_type = analysis_type
        self.days = days
        self.common = common

# 导出格式依赖
class ExportParams:
    """导出参数依赖"""
    
    def __init__(
        self,
        format: str = Query("json", regex="^(json|csv|xlsx)$", description="导出格式"),
        include_columns: Optional[str] = Query(None, description="包含的列（逗号分隔）")
    ):
        self.format = format
        self.include_columns = include_columns.split(",") if include_columns else None

# 响应头依赖
async def add_response_headers():
    """
    添加通用响应头依赖
    """
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Cache-Control": "no-cache, no-store, must-revalidate"
    }

# 数据库事务依赖
async def with_transaction(db: AsyncSession = Depends(get_db)):
    """
    数据库事务依赖
    确保在事务中执行操作
    """
    try:
        # 开始事务
        await db.begin()
        yield db
        # 提交事务
        await db.commit()
    except Exception as e:
        # 回滚事务
        await db.rollback()
        logger.error(f"Transaction failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database transaction failed"
        )
