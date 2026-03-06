from core.exceptions import AppException
import hashlib
import json
from typing import Any, Dict, List
from fastapi import APIRouter, BackgroundTasks, Depends
from core.status_code import StatusCode
from sqlalchemy.ext.asyncio import AsyncSession
from crud import analysis_result as crud_analysis, user_query as crud_user_query, job as crud_job
from schemas.analysis_schema import (
    AnalysisResultInDB, 
    AnalysisResultList, 
    AnalysisResultCreate, 
    UserQueryInDB, 
    UserQueryCreate,
    MajorAnalysisRequest,
    MajorCategory,
)
from common.databases.PostgresManager import db_manager
from core.logger import sys_logger as logger
from dependencies import get_db
from crud.major import major as crud_major
from services.analysis_service import analysis_service
from common.databases.RedisManager import redis_manager
from crud import industry as crud_industry
from schemas.job_schema import JobQueryParams
from dependencies import get_current_user
router = APIRouter()


async def _stable_digest(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


async def _safe_increment_counter(key: str, amount: int = 1) -> None:
    try:
        await redis_manager.increment_counter(key, amount=amount)
    except Exception as exc:
        logger.warning(f"Failed to increment counter {key}: {exc}")

@router.get("/stats")
async def get_job_statistics(
    keyword: str = None,
    industry_name: str = None,
    industry_2_name: str = None,
    job_params: JobQueryParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """获取职位统计数据 (集成 ES 聚合与 Redis 缓存)"""
    search_keyword = keyword or job_params.q

    # 如果是无任何筛选条件的全局统计（首页需要的情况）
    if not any([
        search_keyword,
        job_params.location,
        job_params.experience,
        job_params.education,
        job_params.industry,
        job_params.industry_2,
    ]):
        try:
            return await analysis_service.get_home_stats()
        except Exception as e:
            logger.error(f"ES home stats failed: {e}")
            # 如果首页查挂了，继续往下走 DB fallback 逻辑
            pass

    try:
        return await analysis_service.get_faceted_job_stats(
            keyword=search_keyword,
            location=job_params.location,
            experience=job_params.experience,
            industry=job_params.industry,
            industry_2=job_params.industry_2
        )
    except Exception as e:
        logger.error(f"ES stats failed, falling back to DB: {e}")
        # 降级：从数据库获取统计 (支持筛选)
        return await crud_job.get_statistics_from_db(
            db, 
            keyword=search_keyword,
            location=job_params.location,
            experience=job_params.experience,
            industry=job_params.industry,
            industry_2=job_params.industry_2
        )

@router.get("/skill-cloud")
async def get_skill_cloud(
    keyword: str = None,
    industry: int = None,
    industry_name: str = None,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """获取技能词云数据 (基于 ES 聚合)"""
    if not keyword and not industry:
        return []
    try:
        return await analysis_service.get_skill_cloud_stats(
            keyword=keyword, 
            industry=industry, 
            industry_name=industry_name,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Skill cloud API failed: {e}")
        return []


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
        raise AppException(status_code=StatusCode.NOT_FOUND, code=StatusCode.BUSINESS_ERROR, message="Analysis result not found")
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
        async with await db_manager.get_session() as session:
            # 2. 增加数据库中的热度值
            await crud_major.increment_hot_index(session, major_name=major_name)
            
            # [优化策略]
            # 理由: 热门专业列表不需要实时性，1小时更新一次足够了。
            
            
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
        cache_payload = {
            "major_name": request.major_name,
            "location": request.location,
            "keywords": sorted(request.keywords) if request.keywords else [],
        }
        cache_key = f"analysis:major_skills:{await _stable_digest(cache_payload)}"
        cached_result = await redis_manager.get_cache(cache_key)
        # 2. 如果有缓存，直接返回数据，但扔要异步更新热度
        if cached_result is not None:
            await _safe_increment_counter("metrics:analysis:major_skills:cache_hit")
            if request.major_name:
                # 添加后台任务
                background_tasks.add_task(task_update_major_stats, request.major_name)
            return cached_result
        await _safe_increment_counter("metrics:analysis:major_skills:cache_miss")
        industry_codes = []
        job_type_keywords = []
        major_codes = []
        if request.major_name:
            relation = await crud_major.get_relation_by_major_name(db, request.major_name)
            major_codes = relation.industry_codes
            logger.info(f"Major analysis relation resolved: major={request.major_name}, relation={relation}")

            if relation and relation.industry_codes:
                _, job_type_names = await crud_industry.classify_codes_by_level(db, major_codes)
                if relation.industry_codes:
                    #industry_codes = await crud_industry.get_rollup_codes(db, major_codes,level=1,depth=1)
                    industry_codes = list(set(major_codes + industry_codes))
                if job_type_names:
                    job_type_keywords.extend(job_type_names)


                background_tasks.add_task(task_update_major_stats, request.major_name)
                
        combined_keywords = list(request.keywords) if request.keywords else []
        if job_type_keywords:
            combined_keywords.extend(job_type_keywords)
        combined_keywords.append(request.major_name)
        logger.info(f"Major analysis rollup industry codes: {industry_codes}")
        logger.info(f"Major analysis derived job-type keywords: {combined_keywords}")
        result = await analysis_service.analyze_by_keywords(
            keywords=combined_keywords,
            location=request.location,
            industry_codes=industry_codes,
            major_name=request.major_name
        )
        await redis_manager.set_cache(cache_key, result, expire=14400)
        await _safe_increment_counter("metrics:analysis:major:cache_set")
        return result

    except Exception as e:
        
        logger.error(f"Major analysis failed: {e}")
        raise AppException(status_code=StatusCode.INTERNAL_SERVER_ERROR, code=StatusCode.BUSINESS_ERROR, message="Analysis service unavailable")

from core.cache import cache

@router.get("/major/presets", response_model=List[MajorCategory])
@cache(expire=3600, key_prefix="api:major:presets:v2")
async def get_major_presets(
    db: AsyncSession = Depends(get_db),
):
    """获取专业预设列表 (按分类分组)"""
    
    categories = await crud_major.get_categories_with_children(db)
    
    # 3. 转换格式
    response_data = []
    for cat in categories:
        majors_list = []
        
        for child in cat.children:
            relation = child.industry_relations[0] if child.industry_relations else None
            
            # 使用更清晰的变量提取逻辑
            hot_index = relation.relevance_score if relation and relation.relevance_score else 0
            keywords = relation.keywords if relation and relation.keywords else child.name
            
            majors_list.append({
                "major_name": child.name,
                "keywords": keywords,
                "hot_index": hot_index
            })
        
        # 组装最终的数据结构
        response_data.append({
            "name": cat.name,
            "majors": majors_list
        })

    return response_data

@router.get("/major/industries")
@cache(expire=3600, key_prefix="api:major:industries:v2")
async def get_major_industries(
    major_name: str,
    db: AsyncSession = Depends(get_db),
):
    """
    根据专业名称获取其关联的精确父级行业列表。
    用于做职业罗盘的前置筛选联动。
    """
    if not major_name:
        return []

    relation = await crud_major.get_relation_by_major_name(db, major_name)
    logger.debug(f"Major industries relation resolved: major={major_name}, relation={relation}")
    if not relation or not relation.industry_codes:
        return []
    all_codes = await crud_industry.get_rollup_codes(db, relation.industry_codes,level=0,depth=2)
    logger.debug(f"Major industries rollup codes: {all_codes}")
    industry_trees = await crud_industry.get_industry_trees_by_codes(db, all_codes)

    return industry_trees



