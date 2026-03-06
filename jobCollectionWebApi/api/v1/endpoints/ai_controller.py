"""
AI Controller — 集中管理所有 AI 异步任务端点。

端点列表:
  POST /advice          — AI 职业建议
  POST /career-compass  — 职业罗盘报告
  POST /parse-resume    — 简历智能解析
  GET  /task/{task_id}   — 轮询任务结果 (Redis-first)
  GET  /tasks/history    — 历史记录 (分页)
"""

import hashlib
import json
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, ExternalServiceException
from core.status_code import StatusCode
from core.logger import sys_logger as logger
from dependencies import get_db, get_current_user
from schemas.analysis_schema import AIAdviceRequest, CareerCompassRequest
from schemas.ai_task_schema import AiTaskBrief, AiTaskList
from services.ai_access_service import ai_access_service
from services.analysis_service import analysis_service
from common.databases.RedisManager import redis_manager
from services.ai_service import ai_service
from crud import industry as crud_industry
from crud.major import major as crud_major
from crud import ai_task as crud_ai_task
from config import settings
import os

router = APIRouter()


def _decode_result_data(raw_result_data):
    """Best-effort decode task result_data to structured payload."""
    if isinstance(raw_result_data, dict):
        return raw_result_data
    if isinstance(raw_result_data, str):
        text = raw_result_data.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except Exception:
                return None
    return None


# ═══════════════════════════════════════════════════
# POST /advice — AI 职业建议
# ═══════════════════════════════════════════════════
"""
    获取 AI 职业建议 (异步版: 提交 Celery 任务, 通过轮询或 WebSocket 获取结果)

    【并发限制】同一用户同一时间只能执行一个 career_advice 任务。
    """
@router.post("/advice")
async def get_ai_advice(
    req: AIAdviceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    
    feature_key = "career_advice"

    # 1. 功能开关
    if not settings.AI_ENABLED:
        raise ExternalServiceException(message="AI service is disabled")

    # 2. 并发锁检查 检查是否有任务正在进行
    running_task_id = await crud_ai_task.get_active_task_id(current_user.id, feature_key)
    if running_task_id:
        from core.metrics import ai_task_rejected
        ai_task_rejected.labels(feature=feature_key).inc()
        raise AppException(
            status_code=StatusCode.CONFLICT,
            code=StatusCode.AI_TASK_RUNNING,
            message="当前有任务正在执行中，请等待完成后再提交",
            data={"task_id": running_task_id},
        )

    # 2.5 去重缓存检查
    request_params = {
        "major_name": req.major_name,
        "skills": req.skills,
        "engine": req.engine,
    }
    if req.analysis_params:
        request_params["analysis_params"] = req.analysis_params
    dedup = await crud_ai_task.check_dedup(feature_key, request_params)
    if dedup:
        from core.metrics import ai_task_dedup_hits
        ai_task_dedup_hits.labels(feature=feature_key).inc()
        logger.info(f"AI task dedup hit: {feature_key}, reusing {dedup['celery_task_id']}")
        return {"task_id": dedup["celery_task_id"], "status": "completed", "result": dedup["result"], "cached": True}

    # 3. 前置鉴权与计费校验
    charge_amount = await ai_access_service.ensure_access(
        db=db,
        user_id=current_user.id,
        feature_key=feature_key,
    )

    # 4. 提交 Celery 任务
    from tasks.ai_tasks import career_advice_task
    from core.metrics import celery_tasks_submitted, ai_task_created

    celery_tasks_submitted.labels(task_name="tasks.ai_tasks.career_advice_task", queue="realtime").inc()
    task = career_advice_task.delay(
        user_id=current_user.id,
        major=req.major_name,
        skills=req.skills,
        engine=req.engine or "auto",
        charge_amount=charge_amount,
        analysis_result=req.analysis_result,
    )

    # 5. 写入 AiTask 记录 + 设置 Redis 活跃锁
    await crud_ai_task.create_task(
        db,
        user_id=current_user.id,
        celery_task_id=task.id,
        feature_key=feature_key,
        request_params=request_params,
        analysis_input={
            "analysis_result": req.analysis_result,
            "analysis_params": req.analysis_params,
        },
    )
    await db.commit()
    ai_task_created.labels(feature=feature_key).inc()

    logger.info(
        "ai_task_lifecycle",
        extra={"event": "created", "user_id": current_user.id, "feature_key": feature_key, "celery_task_id": task.id},
    )
    return {"task_id": task.id, "status": "pending"}


# ═══════════════════════════════════════════════════
# POST /career-compass — 职业罗盘
# ═══════════════════════════════════════════════════

@router.post("/career-compass")
async def get_career_compass(
    req: CareerCompassRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    【核心功能】BI 职业数据大盘与 AI 职业罗盘分析 (异步版)
    ES 数据聚合仍在 controller 完成，AI 报告生成提交 Celery 任务。

    【并发限制】同一用户同一时间只能执行一个 career_compass 任务。
    """
    feature_key = "career_compass"

    if not settings.AI_ENABLED or not settings.AI_CAREER_COMPASS_ENABLED:
        raise ExternalServiceException(message="Career compass is disabled")

    # 1. 并发锁检查
    running_task_id = await crud_ai_task.get_active_task_id(current_user.id, feature_key)
    if running_task_id:
        from core.metrics import ai_task_rejected
        ai_task_rejected.labels(feature=feature_key).inc()
        raise AppException(
            status_code=StatusCode.CONFLICT,
            code=StatusCode.AI_TASK_RUNNING,
            message="当前有任务正在执行中，请等待完成后再提交",
            data={"task_id": running_task_id},
        )

    # 2. 计费校验
    charge_amount = await ai_access_service.ensure_access(
        db=db,
        user_id=current_user.id,
        feature_key=feature_key,
    )

    try:
        # 3. 确定搜索关键词与行业
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

        combined_keywords = keywords + job_type_keywords + [req.major_name]
        logger.info(f"combined_keywords: {combined_keywords}")

        # 4. ES 聚合统计
        es_stats = await analysis_service.career_analysis(
            keywords=combined_keywords,
            industry=req.target_industry,
            industry_name=req.target_industry_name,
            major_name=req.major_name,
        )

        # 5. 统一缓存检查
        stats_hash = hashlib.md5(json.dumps(es_stats, sort_keys=True, default=str).encode()).hexdigest()
        cache_key = ai_service.get_ai_cache_key("career_compass", {
            "major": req.major_name,
            "stats_hash": stats_hash,
        })
        cached_report = await redis_manager.get_cache(cache_key)
        if cached_report is not None:
            logger.info(f"Career Compass report CACHE HIT: {cache_key}")
            from core.metrics import ai_cache_hits
            ai_cache_hits.labels(feature="career_compass").inc()
            return {"report": cached_report, "es_stats": es_stats, "cached": True}

        # 6. 提交 Celery 任务
        from tasks.ai_tasks import career_compass_task
        from core.metrics import celery_tasks_submitted, ai_task_created

        celery_tasks_submitted.labels(task_name="tasks.ai_tasks.career_compass_task", queue="realtime").inc()
        task = career_compass_task.delay(
            user_id=current_user.id,
            major_name=req.major_name,
            es_stats=es_stats,
            charge_amount=charge_amount,
            skill_cloud_data=req.skill_cloud_data,
        )

        # 7. 写入 AiTask 记录
        await crud_ai_task.create_task(
            db,
            user_id=current_user.id,
            celery_task_id=task.id,
            feature_key=feature_key,
            request_params={
                "major_name": req.major_name,
                "target_industry": req.target_industry,
                "target_industry_name": req.target_industry_name,
                "target_industry_2": req.target_industry_2,
                "target_industry_2_name": req.target_industry_2_name,
            },
            analysis_input={
                "major_name": req.major_name,
                "es_stats": es_stats,
                "skill_cloud_data": req.skill_cloud_data,
                "target_industry": req.target_industry,
                "target_industry_name": req.target_industry_name,
                "target_industry_2": req.target_industry_2,
                "target_industry_2_name": req.target_industry_2_name,
            },
        )
        await db.commit()
        ai_task_created.labels(feature=feature_key).inc()

        logger.info(
            "ai_task_lifecycle",
            extra={"event": "created", "user_id": current_user.id, "feature_key": feature_key, "celery_task_id": task.id},
        )
        return {"task_id": task.id, "status": "pending", "es_stats": es_stats}

    except AppException:
        raise
    except Exception as e:
        logger.error(f"Career Compass Analysis Failed: {e}")
        raise AppException(status_code=500, code=StatusCode.BUSINESS_ERROR, message="生成职业罗盘报告失败")


# ═══════════════════════════════════════════════════
# POST /parse-resume — 简历解析
# ═══════════════════════════════════════════════════

@router.post("/parse-resume", status_code=202)
async def parse_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    上传简历并异步解析。
    解析完成后将通过 WebSocket 推送 type: resume_parsed 消息。

    【并发限制】同一用户同一时间只能执行一个 resume_parse 任务。
    """
    feature_key = "resume_parse"

    # 1. 文件校验
    if not file.filename.lower().endswith('.pdf'):
        raise AppException(status_code=400, code=StatusCode.PARAMS_ERROR, message="仅支持PDF文件")

    # 2. 并发锁检查
    running_task_id = await crud_ai_task.get_active_task_id(current_user.id, feature_key)
    if running_task_id:
        from core.metrics import ai_task_rejected
        ai_task_rejected.labels(feature=feature_key).inc()
        raise AppException(
            status_code=StatusCode.CONFLICT,
            code=StatusCode.AI_TASK_RUNNING,
            message="当前有简历解析任务正在执行中，请等待完成",
            data={"task_id": running_task_id},
        )

    # 3. 保存文件
    upload_dir = os.path.join(settings.UPLOAD_DIR, "temp_resumes")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{current_user.id}_{file.filename}")
    content = await file.read()
    with open(file_path, "wb") as buffer:
        buffer.write(content)

    # 4. 提交 Celery 任务
    from tasks.resume_parser import parse_resume_task
    from core.metrics import celery_tasks_submitted, ai_task_created

    celery_tasks_submitted.labels(task_name="tasks.resume_parser.parse_resume_task", queue="realtime").inc()
    task_result = parse_resume_task.delay(current_user.id, file_path)

    # 5. 写入 AiTask 记录
    await crud_ai_task.create_task(
        db,
        user_id=current_user.id,
        celery_task_id=task_result.id,
        feature_key=feature_key,
        request_params={"filename": file.filename},
    )
    await db.commit()
    ai_task_created.labels(feature=feature_key).inc()

    logger.info(
        "ai_task_lifecycle",
        extra={"event": "created", "user_id": current_user.id, "feature_key": feature_key, "celery_task_id": task_result.id},
    )
    return {"message": "简历正在解析中，请留意消息通知", "task_id": task_result.id}


# ═══════════════════════════════════════════════════
# GET /task/{task_id} — 轮询结果 (Redis-first)
# ═══════════════════════════════════════════════════

@router.get("/task/{task_id}")
async def get_ai_task_result(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    轮询 AI 任务状态和结果 (Redis-first → PG-fallback → Celery-fallback)。
    """
    # 1. 先查 AiTask 表 (Redis 缓存 → PG)
    task_data = await crud_ai_task.get_task_result(task_id, db=db)
    if task_data:
        status = task_data.get("status", "unknown")
        if status == "completed":
            decoded = _decode_result_data(task_data.get("result_data"))
            if decoded:
                merged_result = {**task_data, **decoded}
                merged_result["result_payload"] = decoded
            else:
                merged_result = task_data
            return {"task_id": task_id, "status": "completed", "result": merged_result}
        elif status == "failed":
            return {"task_id": task_id, "status": "failed", "error": task_data.get("error_message")}
        # pending/processing — 继续检查 Celery 状态
        # （Celery 可能已完成但还没回写，用 Celery 做兜底）

    # 2. Celery result backend 兜底
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


# ═══════════════════════════════════════════════════
# GET /tasks/history — 历史记录 (分页)
# ═══════════════════════════════════════════════════

@router.get("/tasks/history")
async def get_ai_task_history(
    feature_key: str = None,
    page: int = 1,
    page_size: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """查询当前用户的 AI 任务历史列表。"""
    skip = (page - 1) * page_size
    items, total = await crud_ai_task.get_user_history(
        db,
        user_id=current_user.id,
        feature_key=feature_key,
        skip=skip,
        limit=page_size,
    )
    return AiTaskList(
        items=[AiTaskBrief.model_validate(item) for item in items],
        total=total,
        page=page,
        size=page_size,
    )
