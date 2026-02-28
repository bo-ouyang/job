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
from services.ai_access_service import ai_access_service
from config import settings
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

@router.get("/ai_search", summary="AI Intent Search (Async)")
async def ai_search_jobs(
    request: Request,
    background_tasks: BackgroundTasks,
    q: str = Query(..., description="Natural language search describing what you want"),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
    redis: RedisManager = Depends(get_redis),
    current_user: dict = Depends(get_current_user),
):
    """
    通过 AI 自然语言提取意图并动态组装 ES DSL 搜索职位 (异步版)
    缓存命中 → 立即返回 JobList; 缓存未命中 → 提交 Celery 任务, 返回 task_id
    """
    if not settings.AI_ENABLED:
        raise HTTPException(status_code=503, detail="AI service is disabled")

    import hashlib
    # 构造唯一缓存键
    q_hash = hashlib.md5(q.encode('utf-8')).hexdigest()
    cache_key = f"ai_search:q_{q_hash}:page_{pagination.page}:size_{pagination.page_size}"
    
    # Cache hit → return immediately
    cached = await redis.get_cache(cache_key)
    if cached is not None:
        charge_amount = await ai_access_service.ensure_access(
            db=db,
            user_id=current_user.id,
            feature_key="ai_search",
        )
        await ai_access_service.charge_usage(
            db=db,
            user_id=current_user.id,
            feature_key="ai_search",
            amount=charge_amount,
            detail_suffix="cache_hit",
        )
        return JobList(**cached)

    # Cache miss → billing check then submit Celery task
    charge_amount = await ai_access_service.ensure_access(
        db=db,
        user_id=current_user.id,
        feature_key="ai_search",
    )
    
    try:
        from tasks.ai_tasks import ai_search_task
        task = ai_search_task.delay(
            user_id=current_user.id,
            query=q,
            page=pagination.page,
            page_size=pagination.page_size,
            charge_amount=charge_amount,
        )
        
        # 日志审计异步记录
        search_data = {"q": q, "async": True, "task_id": task.id}
        background_tasks.add_task(
            log_search_activity,
            query_type="ai_search",
            params=search_data,
            result_count=0,
            ip=request.client.host,
            ua=request.headers.get("user-agent")
        )

        return {"task_id": task.id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI Search Endpoint Error: {e}")
        raise HTTPException(
            status_code=StatusCode.INTERNAL_SERVER_ERROR,
            detail=f"AI Search Failed: {str(e)}"
        )


@router.get("/ai_search/task/{task_id}", summary="Poll AI Search Task Result")
async def get_ai_search_task_result(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """轮询 AI 搜索任务状态和结果"""
    from core.celery_app import celery_app
    result = celery_app.AsyncResult(task_id)
    
    if result.state == "PENDING":
        return {"task_id": task_id, "status": "pending"}
    elif result.state == "STARTED":
        return {"task_id": task_id, "status": "processing"}
    elif result.state == "SUCCESS":
        return {"task_id": task_id, "status": "completed", "result": result.result}
    elif result.state == "FAILURE":
        return {"task_id": task_id, "status": "failed", "error": str(result.result)}
    else:
        return {"task_id": task_id, "status": result.state.lower()}


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
async def test_ai_parse(
    request: AIParseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    接收自然语言，返回 AI 解析出的结构化搜索意图 JSON。
    用于调试 prompt 以及检验 Pydantic Schema 的覆盖率。
    """
    try:
        if not settings.AI_ENABLED:
            raise HTTPException(status_code=503, detail="AI service is disabled")
        charge_amount = await ai_access_service.ensure_access(
            db=db,
            user_id=current_user.id,
            feature_key="ai_search",
        )
        parsed_intent = await ai_service.parse_job_search_intent(request.query)
        await ai_access_service.charge_usage(
            db=db,
            user_id=current_user.id,
            feature_key="ai_search",
            amount=charge_amount,
        )
        return {
            "query": request.query,
            "parsed_intent": parsed_intent
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing AI intent: {e}")
        raise HTTPException(
            status_code=StatusCode.INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse query via AI: {e}"
        )
