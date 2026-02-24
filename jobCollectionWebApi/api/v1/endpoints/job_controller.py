from fastapi import APIRouter, Depends, HTTPException, Query, status, Request, BackgroundTasks
from core.status_code import StatusCode
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies import get_db
from crud import job as crud_job
from crud.analysis import user_query
from schemas.job import *
from schemas.analysis import UserQueryCreate
from common.databases.PostgresManager import db_manager
from dependencies import (
    get_db, 
    PaginationParams, 
    SearchParams,
    JobQueryParams,
    get_current_user,
    get_admin_user,
    rate_limiter,
    verify_db_health,
    RateLimiter,
    get_cache_key 
)
from common.databases.RedisManager import RedisManager, get_redis
from core.logger import sys_logger as logger
router = APIRouter()
strict_limit = RateLimiter(requests_per_minute=10)

# 搜索引擎服务注入
from services.search_service import search_service
from services.ai_service import ai_service
from pydantic import BaseModel

class AIParseRequest(BaseModel):
    query: str

async def log_search_activity(
    query_type: str, 
    params: dict, 
    result_count: int, 
    ip: str, 
    ua: str, 
    user_id: Optional[int] = None
):
    """异步记录用户搜索记录"""
    try:
        async with db_manager.async_session() as db:
            obj_in = UserQueryCreate(
                query_type=query_type,
                parameters=params,
                result_count=result_count,
                user_id=user_id,
                user_ip=ip,
                user_agent=ua
            )
            await user_query.create(db, obj_in=obj_in)
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log search: {e}")

from core.cache import cache

@router.get("/ai_search", response_model=JobList, summary="AI Intent Search")
async def ai_search_jobs(
    request: Request,
    background_tasks: BackgroundTasks,
    q: str = Query(..., description="Natural language search describing what you want"),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    redis: RedisManager = Depends(get_redis)
):
    """
    通过 AI 自然语言提取意图并动态组装 ES DSL 搜索职位
    """
    import hashlib
    # 构造唯一缓存键 (不再复用包含深度依赖反射的 get_cache_key)
    q_hash = hashlib.md5(q.encode('utf-8')).hexdigest()
    cache_key = f"ai_search:q_{q_hash}:page_{pagination.page}:size_{pagination.page_size}"
    
    cached = await redis.get_cache(cache_key)
    if cached:
        return JobList(**cached)

    try:
        # 1. 拦截解析自然意图
        parsed_intent = await ai_service.parse_job_search_intent(q)
        
        # 2. 交由 ES + PG 容灾双重搜索服务处理结构化的 JSON 意图
        jobs, total = await search_service.search_jobs_by_ai_intent(
            intent=parsed_intent,
            skip=pagination.skip,
            limit=pagination.page_size
        )
        
        result = JobList(
            items=jobs,
            total=total,
            page=pagination.page,
            size=pagination.page_size,
            pages=(total + pagination.page_size - 1) // pagination.page_size
        )
        
        # 3. 数据写入缓存体系 (有效10分钟)
        await redis.set_cache(cache_key, result.model_dump(mode='json'), expire=600)
        
        # 4. 日志审计异步记录
        search_data = {
            "q": q,
            "parsed_intent": parsed_intent
        }
        background_tasks.add_task(
            log_search_activity,
            query_type="ai_search",
            params=search_data,
            result_count=total,
            ip=request.client.host,
            ua=request.headers.get("user-agent")
        )

        return result
    except Exception as e:
        logger.error(f"AI Search Endpoint Error: {e}")
        raise HTTPException(
            status_code=StatusCode.INTERNAL_SERVER_ERROR,
            detail=f"AI Search Failed: {str(e)}"
        )

@router.get("/jobs", response_model=JobList)
@cache(expire=300)
async def read_jobs(
    request: Request,
    background_tasks: BackgroundTasks,
    job_params: JobQueryParams = Depends(),
    db: AsyncSession = Depends(get_db),
    # redis: RedisManager = Depends(get_redis), # 装饰器内部使用全局 redis_manager
    _: bool = Depends(strict_limit),
    current_user: dict = Depends(get_current_user)
):
    """获取职位列表 (集成 ES 搜索与 Redis 缓存)"""
    # 记录日志到中间件所需的 state (如果认证成功)
    request.state.user_id = current_user.id
    
    # 1. 从 Elasticsearch 搜索
    try:
        jobs, total = await search_service.search_jobs(
            keyword=job_params.common.search.q,
            location=job_params.location,
            experience=job_params.experience,
            education=job_params.education,
            industry=job_params.industry,
            salary_min=job_params.salary_min,
            salary_max=job_params.salary_max,
            skip=job_params.common.pagination.skip,
            limit=job_params.common.pagination.page_size
        )
    except Exception as e:
        logger.error(f"ES search failed, falling back to DB: {e}")
        # 降级：从数据库搜索
        jobs, total = await crud_job.search(
            db,
            keyword=job_params.common.search.q,
            location=job_params.location,
            experience=job_params.experience,
            education=job_params.education,
            industry=job_params.industry,
            salary_min=job_params.salary_min,
            salary_max=job_params.salary_max,
            skip=job_params.common.pagination.skip,
            limit=job_params.common.pagination.page_size
        )
    
    # DEBUG
    if jobs:
        print(f"DEBUG: jobs[0] type: {type(jobs[0])}", flush=True)
        if hasattr(jobs[0], 'industry'):
             print(f"DEBUG: jobs[0].industry: {jobs[0].industry}", flush=True)
             if jobs[0].industry:
                 print(f"DEBUG: jobs[0].industry type: {type(jobs[0].industry)}", flush=True)
                 if hasattr(jobs[0].industry, '__dict__'):
                     print(f"DEBUG: jobs[0].industry dict: {jobs[0].industry.__dict__}", flush=True)
    
    # 2. 构造结果
    result = JobList(
        items=jobs,
        total=total,
        page=job_params.common.pagination.page,
        size=job_params.common.pagination.page_size,
        pages=(total + job_params.common.pagination.page_size - 1) // job_params.common.pagination.page_size
    )
    
    # 3. 记录搜索日志 (异步后台任务)
    if job_params.common.search.q:
        search_data = {
            "q": job_params.common.search.q,
            "sort": job_params.common.search.sort,
            "order": job_params.common.search.order
        }
        background_tasks.add_task(
            log_search_activity,
            query_type="job_search",
            params=search_data,
            result_count=total,
            ip=request.client.host,
            ua=request.headers.get("user-agent"),
            user_id=current_user.id
        )

    return result

@router.get("/{job_id}", response_model=JobWithRelations)
@cache(expire=3600)
async def read_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取职位详情"""
    db_job = await crud_job.get_with_relations(db, id=job_id)
    if not db_job:
        raise HTTPException(
            status_code=StatusCode.NOT_FOUND,
            detail="Job not found"
        )
    return db_job

@router.post("", response_model=JobInDB)
async def create_job(
    job_in: JobCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建职位"""
    # 检查来源URL是否已存在
    if job_in.source_url:
        existing_job = await crud_job.get_by_source_url(db, source_url=job_in.source_url)
        if existing_job:
            raise HTTPException(
                status_code=StatusCode.BAD_REQUEST,
                detail="Job with this source URL already exists"
            )
    
    return await crud_job.create(db, obj_in=job_in)

@router.post("update/{job_id}", response_model=JobInDB)
async def update_job(
    job_id: int,
    job_in: JobUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新职位"""
    db_job = await crud_job.get(db, id=job_id)
    if not db_job:
        raise HTTPException(
            status_code=StatusCode.NOT_FOUND,
            detail="Job not found"
        )
    
    return await crud_job.update(db, db_obj=db_job, obj_in=job_in)

@router.post("/delete/{job_id}")
async def delete_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: dict = Depends(get_admin_user)
):
    """删除职位（需要管理员权限）"""
    job = await crud_job.remove(db, id=job_id)
    if not job:
        raise HTTPException(status_code=StatusCode.NOT_FOUND, detail="Job not found")
    return {"message": "Job deleted successfully"}


@router.get("/skills/{skill_names}", response_model=List[JobInDB])
async def read_jobs_by_skills(
    skill_names: str,
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """根据技能获取职位"""
    skills_list = [name.strip() for name in skill_names.split(",")]
    return await crud_job.get_by_skills(
        db, skill_names=skills_list, skip=skip, limit=limit
    )


# 公开接口（不需要认证）
@router.get("/public/jobs", response_model=JobList)
async def read_public_jobs(
    request: Request,
    background_tasks: BackgroundTasks,
    pagination: PaginationParams = Depends(),
    search: SearchParams = Depends(),
    db: AsyncSession = Depends(get_db),
    redis: RedisManager = Depends(get_redis)
):
    """获取公开职位列表 (ES 驱动，不需要认证)"""
    # 1. 缓存 key
    cache_key = get_cache_key("public_jobs", pagination=pagination, search=search)
    
    cached = await redis.get_cache(cache_key)
    if cached:
        return JobList(**cached)

    # 2. 从 ES 搜索 (仅支持基础关键词)
    try:
        jobs, total = await search_service.search_jobs(
            keyword=search.q,
            skip=pagination.skip,
            limit=pagination.page_size
        )
    except Exception as e:
        logger.error(f"ES public search failed, falling back to DB: {e}")
        # 降级：从数据库搜索
        jobs, total = await crud_job.search(
            db,
            keyword=search.q,
            skip=pagination.skip,
            limit=pagination.page_size
        )
    
    result = JobList(
        items=jobs,
        total=total,
        page=pagination.page,
        size=pagination.page_size,
        pages=(total + pagination.page_size - 1) // pagination.page_size
    )
    
    # 3. 写入缓存
    await redis.set_cache(cache_key, result.model_dump(mode='json'), expire=600)
    
    # 4. 记录搜索日志 (公共搜索不带用户ID)
    if search.q:
        search_data = {
            "q": search.q,
            "sort": search.sort,
            "order": search.order
        }
        background_tasks.add_task(
            log_search_activity,
            query_type="public_search",
            params=search_data,
            result_count=total,
            ip=request.client.host,
            ua=request.headers.get("user-agent")
        )

    return result

@router.post("/test_ai_parse", summary="Test AI Intent Parsing")
async def test_ai_parse(request: AIParseRequest):
    """
    接收自然语言，返回 AI 解析出的结构化搜索意图 JSON。
    用于调试 prompt 以及检验 Pydantic Schema 的覆盖率。
    """
    try:
        parsed_intent = await ai_service.parse_job_search_intent(request.query)
        return {
            "query": request.query,
            "parsed_intent": parsed_intent
        }
    except Exception as e:
        logger.error(f"Error parsing AI intent: {e}")
        raise HTTPException(
            status_code=StatusCode.INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse query via AI: {e}"
        )