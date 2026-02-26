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
    AIAdviceRequest,
    CareerCompassRequest
)
from common.databases.PostgresManager import db_manager
from core.logger import sys_logger as logger
from dependencies import get_db, JobQueryParams,get_current_user
from crud.major import major as crud_major
from fastapi import BackgroundTasks
from services.analysis_service import analysis_service
from common.databases.RedisManager import redis_manager
from services.ai_service import ai_service
from crud import industry as crud_industry
from sqlalchemy import select
from common.databases.models.industry import Industry
router = APIRouter()

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
        job_type_keywords = []
        if request.major_name:
            # 1. Fetch Industry Codes for Major
            relation = await crud_major.get_relation_by_major_name(db, request.major_name)
            print(f"Major: {request.major_name}, Relation: {relation}")
            if relation and relation.industry_codes:
                # Classify codes: level 0/1 for industry filtering, level >= 2 for keyword filtering
                
                _, job_type_names = await crud_industry.classify_codes_by_level(db, relation.industry_codes)
                

                # Rollup level 0/1 codes to match jobs table granularity
                if relation.industry_codes:
                    industry_codes = await crud_industry.get_rollup_codes(db, relation.industry_codes,level=0)
                
                # Add level >= 2 names to keywords
                if job_type_names:
                    job_type_keywords.extend(job_type_names)
                    
                print(f"Industry Codes (Level 0/1): {industry_codes}")
                print(f"Job Type Keywords (Level >= 2): {job_type_keywords}")
            

                background_tasks.add_task(task_update_major_stats, request.major_name)

        # Merge original keywords with dynamically extracted job type names
        combined_keywords = list(request.keywords) if request.keywords else []
        if job_type_keywords:
            combined_keywords.extend(job_type_keywords)

        # 3. Analyze (ES First, DB Fallback)
        result = await analysis_service.analyze_by_keywords(
            keywords=combined_keywords,
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

from core.cache import cache

@router.get("/major/presets", response_model=List[MajorCategory])
@cache(expire=3600, key_prefix="api:major:presets:v2")
async def get_major_presets(
    db: AsyncSession = Depends(get_db),
):
    """获取专业预设列表 (按分类分组)"""
    
    # 2. 缓存未命中，查数据库 (确保这个方法使用了上面提到的 selectinload)
    categories = await crud_major.get_categories_with_children(db)
    
    # 3. 转换格式
    response_data = []
    for cat in categories:
        majors_list = []
        
        # 遍历子专业 (因为预加载了，这里绝对不会触发新的 SQL)
        for child in cat.children:
            # 安全获取 relation：如果列表有数据则取第一个，否则为 None
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

    # 1. 找到该专业的 industry_codes
    relation = await crud_major.get_relation_by_major_name(db, major_name)
    print(f"Major: {major_name}, Relation: {relation}")
    if not relation or not relation.industry_codes:
        return []
    all_codes = await crud_industry.get_rollup_codes(db, relation.industry_codes,level=0)
    print(f"All Codes: {all_codes}")
    industry_trees = await crud_industry.get_industry_trees_by_codes(db, all_codes)

    return industry_trees

@router.post("/ai/advice")
async def get_ai_advice(req: AIAdviceRequest):
    """获取 AI 职业建议"""
    return await ai_service.generate_career_advice(req.major_name, req.skills)

@router.post("/career-compass")
async def get_career_compass(
    req: CareerCompassRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    【核心功能】BI职业数据大盘与 AI 职业罗盘分析
    根据专业名称，聚合ES中的职位数据，并交由大模型生成诊断报告。
    """
    cache_key = f"analysis:career_compass:v1:{req.major_name}:{req.target_industry or 'all'}:{req.target_industry_2 or 'all'}"
    cached_report = await redis_manager.get_cache(cache_key)
    if cached_report:
        return {"report": cached_report}
        
    try:
        # 1. 确定搜索关键词与行业
        keywords = []
        # 根据专业名获取预设关键词 (如果关联了专业，顺便把 level >= 2 的精准岗位也解析为关键词)
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
                
        # 2. 从 ES 获取客观聚合数据
        main_keyword = combined_keywords[0] if combined_keywords else req.major_name
        # To avoid passing complex lists to ES, we use the primary keyword
        # and explicitly pass the target_industry (int code) to the ES filtering
        es_stats = await analysis_service.get_job_stats(
            keyword=main_keyword, 
            industry=req.target_industry,
            industry_name=req.target_industry_name,
            industry_2_name=req.target_industry_2_name,
            #industry_2=req.target_industry_2
        )
        
        # 3. 将客观数据交由大模型生成深度分析报告
        ai_report = await ai_service.get_career_navigation_report(
            major_name=req.major_name, 
            es_stats=es_stats
        )
        
        # 4. 写入缓存 (12小时)
        if not ai_report.startswith("❌"):
             await redis_manager.set_cache(cache_key, ai_report, expire=43200)
             
        return {"report": ai_report}
        
    except Exception as e:
        logger.error(f"Career Compass Analysis Failed: {e}")
        raise HTTPException(status_code=500, detail="生成职业罗盘报告失败")
