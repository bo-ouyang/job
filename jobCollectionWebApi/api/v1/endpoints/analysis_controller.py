import hashlib
import json
from typing import Any, Dict, List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
    AIAdviceRequest,
    CareerCompassRequest
)
from common.databases.PostgresManager import db_manager
from core.logger import sys_logger as logger
from dependencies import JobQueryParams, get_current_user, get_db
from crud.major import major as crud_major
from services.analysis_service import analysis_service
from services.ai_access_service import ai_access_service
from common.databases.RedisManager import redis_manager
from services.ai_service import ai_service
from crud import industry as crud_industry
from config import settings
router = APIRouter()


def _stable_digest(payload: Dict[str, Any]) -> str:
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
    industry_name: str = None,
    industry_2_name: str = None,
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
            industry_name=industry_name,
            industry_2_name=industry_2_name,
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

@router.get("/skill-cloud")
async def get_skill_cloud(
    keyword: str = None,
    industry: int = None,
    industry_2: int = None,
    industry_name: str = None,
    industry_2_name: str = None,
    limit: int = 20,
):
    """获取技能词云数据 (基于 ES 聚合)"""
    if not keyword and not industry:
        return []
    try:
        return await analysis_service.get_skill_cloud_stats(
            keyword=keyword, 
            industry=industry, 
            industry_2=industry_2, 
            industry_name=industry_name,
            industry_2_name=industry_2_name,
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
        cache_key = f"analysis:major:v3:{_stable_digest(cache_payload)}"
        cached_result = await redis_manager.get_cache(cache_key)
        # 2. 如果有缓存，直接返回数据，但扔要异步更新热度
        if cached_result is not None:
            await _safe_increment_counter("metrics:analysis:major:cache_hit")
            if request.major_name:
                # 添加后台任务
                background_tasks.add_task(task_update_major_stats, request.major_name)
            return cached_result
        await _safe_increment_counter("metrics:analysis:major:cache_miss")
        industry_codes = []
        job_type_keywords = []
        if request.major_name:
            # 1. ??????????????
            relation = await crud_major.get_relation_by_major_name(db, request.major_name)
            logger.debug(f"Major analysis relation resolved: major={request.major_name}, relation={relation}")
            if relation and relation.industry_codes:
                # ???????????0/1 ??????2 ???????????
                
                _, job_type_names = await crud_industry.classify_codes_by_level(db, relation.industry_codes)
                

                if relation.industry_codes:
                    industry_codes = await crud_industry.get_rollup_codes(db, relation.industry_codes,level=1,depth=2)
                
                # ? 2 ??????????????
                if job_type_names:
                    job_type_keywords.extend(job_type_names)
                    
                logger.debug(f"Major analysis rollup industry codes: {industry_codes}")
                logger.debug(f"Major analysis derived job-type keywords: {job_type_keywords}")
            

                background_tasks.add_task(task_update_major_stats, request.major_name)

        # ????????????????????
        combined_keywords = list(request.keywords) if request.keywords else []
        if job_type_keywords:
            combined_keywords.extend(job_type_keywords)

        result = await analysis_service.analyze_by_keywords(
            keywords=combined_keywords,
            location=request.location,
            industry_codes=industry_codes
        )
        await redis_manager.set_cache(cache_key, result, expire=14400)
        await _safe_increment_counter("metrics:analysis:major:cache_set")
        return result

    except Exception as e:
        
        logger.error(f"Major analysis failed: {e}")
        raise HTTPException(
            status_code=StatusCode.INTERNAL_SERVER_ERROR, 
            detail="Analysis service unavailable"
        )

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

@router.post("/ai/advice")
async def get_ai_advice(
    req: AIAdviceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取 AI 职业建议 (异步版: 提交 Celery 任务, 通过轮询或 WebSocket 获取结果)"""
    if not settings.AI_ENABLED:
        raise HTTPException(status_code=503, detail="AI service is disabled")
    charge_amount = await ai_access_service.ensure_access(
        db=db,
        user_id=current_user.id,
        feature_key="career_advice",
    )
    from tasks.ai_tasks import career_advice_task
    task = career_advice_task.delay(
        user_id=current_user.id,
        major=req.major_name,
        skills=req.skills,
        engine=req.engine or "auto",
        charge_amount=charge_amount,
    )
    return {"task_id": task.id, "status": "pending"}


@router.post("/career-compass")
async def get_career_compass(
    req: CareerCompassRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    【核心功能】BI职业数据大盘与 AI 职业罗盘分析 (异步版)
    ES 数据聚合仍在 controller 完成，AI 报告生成提交 Celery 任务。
    """
    if not settings.AI_ENABLED or not settings.AI_CAREER_COMPASS_ENABLED:
        raise HTTPException(status_code=503, detail="Career compass is disabled")

    cache_payload = {
        "major_name": req.major_name,
        "target_industry": req.target_industry,
        "target_industry_2": req.target_industry_2,
    }
    cache_key = f"analysis:career_compass:v2:{_stable_digest(cache_payload)}"
    cached_report = await redis_manager.get_cache(cache_key)
    if cached_report is not None:
        await _safe_increment_counter("metrics:ai:career_compass:cache_hit")
        return {"report": cached_report}
    await _safe_increment_counter("metrics:ai:career_compass:cache_miss")
    charge_amount = await ai_access_service.ensure_access(
        db=db,
        user_id=current_user.id,
        feature_key="career_compass",
    )
        
    try:
        # 1. 确定搜索关键词与行业 (fast, stays in controller)
        keywords = []
        relation = await crud_major.get_relation_by_major_name(db, req.major_name)
        
        job_type_keywords = []
        if relation:
            if relation.keywords:
                keywords = [k.strip() for k in relation.keywords.split(',')]
                
            if relation.industry_codes:
                _, job_type_names = await crud_industry.classify_codes_by_level(db, relation.industry_codes)
                if job_type_names:
                    job_type_keywords.extend(job_type_names)

        if not keywords and not job_type_keywords:
            keywords = [req.major_name]
            
        combined_keywords = keywords + job_type_keywords
                
        main_keyword = combined_keywords[0] if combined_keywords else req.major_name
        es_stats = await analysis_service.get_job_stats(
            keyword=main_keyword, 
            industry=req.target_industry,
            industry_name=req.target_industry_name,
            industry_2_name=req.target_industry_2_name,
        )
        
        # 2. 提交 AI 报告生成为 Celery 任务
        from tasks.ai_tasks import career_compass_task
        task = career_compass_task.delay(
            user_id=current_user.id,
            major_name=req.major_name,
            es_stats=es_stats,
            charge_amount=charge_amount,
        )
        return {"task_id": task.id, "status": "pending", "es_stats": es_stats}
        
    except HTTPException:
        raise
    except Exception as e:
        await _safe_increment_counter("metrics:ai:career_compass:exceptions")
        logger.error(f"Career Compass Analysis Failed: {e}")
        raise HTTPException(status_code=500, detail="生成职业罗盘报告失败")


@router.get("/ai/task/{task_id}")
async def get_ai_task_result(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """轮询 AI 任务状态和结果 (适用于 career_advice, career_compass)"""
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
