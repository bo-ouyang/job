from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from core.status_code import StatusCode
from sqlalchemy.ext.asyncio import AsyncSession
from crud import analysis_result as crud_analysis, user_query as crud_user_query, job as crud_job
from schemas.analysis import (
    AnalysisResultInDB, 
    AnalysisResultList, 
    AnalysisResultCreate, 
    UserQueryInDB, 
    UserQueryCreate,
    MajorAnalysisRequest,
    MajorCategory,
    AIAdviceRequest
)
from common.databases.PostgresManager import db_manager
from core.logger import sys_logger as logger
from dependencies import get_db, JobQueryParams
from crud.major import major as crud_major
from fastapi import BackgroundTasks
from services.analysis_service import analysis_service
from common.databases.RedisManager import redis_manager
from services.ai_service import ai_service

router = APIRouter()

@router.get("/stats")
async def get_job_statistics(
    job_params: JobQueryParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """获取职位统计数据 (集成 ES 聚合与 Redis 缓存)"""
    try:
        return await analysis_service.get_job_stats(
            keyword=job_params.common.search.q,
            location=job_params.location,
            experience=job_params.experience,
            education=job_params.education,
            industry=job_params.industry,
            industry_2=job_params.industry_2,
            salary_min=job_params.salary_min,
            salary_max=job_params.salary_max,
        )
    except Exception as e:
        logger.error(f"ES stats failed, falling back to DB: {e}")
        # 降级：从数据库获取统计 (支持筛选)
        return await crud_job.get_statistics_from_db(
            db, 
            keyword=job_params.common.search.q,
            location=job_params.location,
            experience=job_params.experience,
            education=job_params.education,
            industry=job_params.industry,
            industry_2=job_params.industry_2,
            salary_min=job_params.salary_min,
            salary_max=job_params.salary_max
        )

@router.get("/results", response_model=AnalysisResultList)
async def read_analysis_results(
    analysis_type: str = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """获取分析结果列表"""
    if analysis_type:
        results = await crud_analysis.get_latest_by_type(
            db, analysis_type=analysis_type, limit=limit
        )
        total = len(results)
    else:
        results = await crud_analysis.get_multi(db, skip=skip, limit=limit)
        total = await crud_analysis.count(db)
    
    return AnalysisResultList(
        items=results,
        total=total,
        page=skip // limit + 1,
        size=limit,
        pages=(total + limit - 1) // limit
    )

@router.post("/results", response_model=AnalysisResultInDB)
async def create_analysis_result(
    analysis_in: AnalysisResultCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建分析结果"""
    return await crud_analysis.create(db, obj_in=analysis_in)

@router.get("/results/{result_id}", response_model=AnalysisResultInDB)
async def read_analysis_result(
    result_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取分析结果详情"""
    db_result = await crud_analysis.get(db, id=result_id)
    if not db_result:
        raise HTTPException(
            status_code=StatusCode.NOT_FOUND,
            detail="Analysis result not found"
        )
    return db_result

@router.post("/queries", response_model=UserQueryInDB)
async def create_user_query(
    query_in: UserQueryCreate,
    db: AsyncSession = Depends(get_db),
):
    """记录用户查询"""
    return await crud_user_query.create(db, obj_in=query_in)

@router.get("/queries", response_model=List[UserQueryInDB])
async def read_user_queries(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """获取用户查询记录"""
    return await crud_user_query.get_recent_queries(db, limit=limit)


async def task_update_major_stats(major_name: str):
    """
    后台异步任务：更新专业热度
    注意：必须使用独立的 db_session，因为请求结束时原 session 会关闭
    """
    if not major_name:
        return

    try:
        # 1. 获取一个新的数据库会话 (Context Manager)
        async with await db_manager.get_session() as session:
            # 2. 增加数据库中的热度值
            await crud_major.increment_hot_index(session, major_name=major_name)
            
            # [优化策略]
            # 方案 A: 彻底不删缓存，等待 naturally expire (推荐，性能最高)
            # 理由: 热门专业列表不需要实时性，1小时更新一次足够了。
            # 如果这里执行 delete_cache，高并发下 Redis 会被击穿。
            
            # 方案 B (可选): 仅更新 Redis 计数器，不操作 DB (如果需要极高性能)
            # await redis_manager.incr(f"stats:major:{major_name}")
            
            logger.info(f"Background task: Incremented hot index for {major_name}")

    except Exception as e:
        logger.error(f"Background task failed for major {major_name}: {e}")

@router.post("/major/analyze")
async def analyze_major_skills(
    request: MajorAnalysisRequest,
    background_tasks: BackgroundTasks, # 注入后台任务
    db: AsyncSession = Depends(get_db),
    
):
    """
    专业技能需求分析接口
    接受一组关键词(如专业相关职位: ["Java开发", "后端工程师"])
    返回聚合分析结果(薪资, 技能, 行业)
    """
    try:
        # 1. [性能优化] 优先检查分析结果缓存 (Redis)
        # 缓存 Key 包含：专业名 + 城市 (Bumped to v2 to clear buggy empty cache)
        cache_key = f"analysis:major:v2:{request.major_name}:{request.location or 'all'}"
        cached_result = await redis_manager.get_cache(cache_key)
        
        # 2. 如果有缓存，直接返回数据，但扔要异步更新热度
        if cached_result:
            if request.major_name:
                # 添加后台任务
                background_tasks.add_task(task_update_major_stats, request.major_name)
            return cached_result
        industry_codes = []
        if request.major_name:
            # 1. Fetch Industry Codes for Major
            relation = await crud_major.get_relation_by_major_name(db, request.major_name)
            print(f"Major: {request.major_name}, Relation: {relation}")
            if relation and relation.industry_codes:
                # Rollup codes to level 0/1 to match jobs table granularity
                from crud import industry as crud_industry
                industry_codes = await crud_industry.get_rollup_codes(db, relation.industry_codes)
                print(f"Industry Codes: {industry_codes}")
            

                background_tasks.add_task(task_update_major_stats, request.major_name)

        # 3. Analyze (DB Only)
        # Directly use CRUD analysis which is SQL optimized
        result = await crud_job.analyze_by_keywords(
            db,
            keywords=request.keywords,
            location=request.location,
            industry_codes=industry_codes
        )
        await redis_manager.set_cache(cache_key, result, expire=14400)
        return result

    except Exception as e:
        
        logger.error(f"Major analysis failed: {e}")
        raise HTTPException(
            status_code=StatusCode.INTERNAL_SERVER_ERROR, 
            detail="Analysis service unavailable"
        )

@router.get("/major/presets", response_model=List[MajorCategory])
async def get_major_presets(
    db: AsyncSession = Depends(get_db),
):
    """获取专业预设列表 (按分类分组)"""
    # 1. 优先查缓存 (Redis)
    cache_key = "api:major:presets:v2" 
    cached_data = await redis_manager.get_cache(cache_key)
    if cached_data:
        return cached_data
    
    # 2. 缓存未命中，查数据库 (Using new nested Major structure)
    categories = await crud_major.get_categories_with_children(db)
    
    # 3. 转换格式
    response_data = []
    for cat in categories:
        majors_list = []
        for child in cat.children:
            # Get relation (Assuming 1-to-1 or taking first)
            relation = child.industry_relations[0] if child.industry_relations else None
            
            item = {
                "major_name": child.name,
                "keywords": relation.keywords if relation and relation.keywords else child.name, # Fallback to name
                "hot_index": relation.relevance_score if relation else 0
            }
            majors_list.append(item)
        
        response_data.append({
            "name": cat.name,
            "majors": majors_list
        })

    # 4. 写入缓存
    await redis_manager.set_cache(cache_key, response_data, expire=3600)

    return response_data

@router.post("/ai/advice")
async def get_ai_advice(req: AIAdviceRequest):
    """获取 AI 职业建议"""
    return await ai_service.generate_career_advice(req.major_name, req.skills)
