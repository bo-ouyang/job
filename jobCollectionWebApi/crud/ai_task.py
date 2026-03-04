"""
AI 任务 CRUD — Redis-first 查询 + 并发锁 + PG 持久化 + 去重缓存

Redis key 设计:
  ai_task:active:{feature_key}:{user_id}    → celery_task_id  (TTL 300s, 并发锁)
  ai_task:result:{celery_task_id}           → JSON 序列化结果  (TTL 3600s, 结果缓存)
  ai_task:dedup:{feature_key}:{params_hash} → celery_task_id  (TTL 3600s, 去重缓存)
"""

import hashlib
import json
import time
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, update, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from common.databases.models.ai_task import AiTask
from common.databases.RedisManager import redis_manager
from core.logger import sys_logger as logger


# ─── 常量 ────────────────────────────────────────
LOCK_TTL = 300       # 活跃锁 5 分钟自动过期（兜底防死锁）
RESULT_TTL = 3600    # 完成结果缓存 1 小时
DEDUP_TTL = 3600     # 去重缓存 1 小时

_ACTIVE_PREFIX = "ai_task:active"
_RESULT_PREFIX = "ai_task:result"
_DEDUP_PREFIX = "ai_task:dedup"


# ─── Redis Key 构建 ─────────────────────────────
def _active_key(feature_key: str, user_id: int) -> str:
    return f"{_ACTIVE_PREFIX}:{feature_key}:{user_id}"


def _result_key(celery_task_id: str) -> str:
    return f"{_RESULT_PREFIX}:{celery_task_id}"


def _dedup_key(feature_key: str, params_hash: str) -> str:
    return f"{_DEDUP_PREFIX}:{feature_key}:{params_hash}"


def _hash_params(params: dict) -> str:
    """对请求参数生成稳定的 MD5 摘要用于去重比对"""
    serialized = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


# ─── 去重缓存 ────────────────────────────────────

async def check_dedup(feature_key: str, request_params: dict) -> Optional[dict]:
    """
    检查相同参数是否在近 1 小时内已有完成的任务。
    命中时返回 {'celery_task_id': ..., 'result': ...}，未命中返回 None。
    """
    if not request_params:
        return None

    params_hash = _hash_params(request_params)

    # 1. Redis 去重缓存
    try:
        rkey = redis_manager.make_key(_dedup_key(feature_key, params_hash))
        cached_task_id = await redis_manager.redis_client.get(rkey)
        if cached_task_id:
            # 查结果
            result = await get_task_result(cached_task_id)
            if result and result.get("status") == "completed":
                return {"celery_task_id": cached_task_id, "result": result}
    except Exception as exc:
        logger.warning(f"Redis dedup check degraded: {exc}")

    return None


async def set_dedup_cache(feature_key: str, request_params: dict, celery_task_id: str) -> None:
    """任务完成后写入去重缓存"""
    if not request_params:
        return
    params_hash = _hash_params(request_params)
    try:
        rkey = redis_manager.make_key(_dedup_key(feature_key, params_hash))
        await redis_manager.redis_client.setex(rkey, DEDUP_TTL, celery_task_id)
    except Exception as exc:
        logger.warning(f"Redis dedup cache write degraded: {exc}")


# ─── 公开 API ───────────────────────────────────

async def create_task(
    db: AsyncSession,
    *,
    user_id: int,
    celery_task_id: str,
    feature_key: str,
    request_params: dict = None,
) -> AiTask:
    """
    创建 AI 任务记录 + 设置 Redis 活跃锁。
    锁使用 SET NX EX 保证原子性：如果已有活跃任务，此函数不会被调用（由调用者先检查）。
    """
    # 1. PG 持久化
    task = AiTask(
        user_id=user_id,
        celery_task_id=celery_task_id,
        feature_key=feature_key,
        status="pending",
        request_params=request_params,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)

    # 2. Redis 活跃锁
    try:
        key = redis_manager.make_key(_active_key(feature_key, user_id))
        await redis_manager.redis_client.set(key, celery_task_id, nx=True, ex=LOCK_TTL)
    except Exception as exc:
        logger.warning(f"Redis set active lock degraded: {exc}")

    return task


async def get_active_task_id(user_id: int, feature_key: str) -> Optional[str]:
    """
    查询用户是否有进行中的任务（纯 Redis，极快）。
    Redis 不可用时降级到 PG。
    返回 celery_task_id 或 None。
    """
    try:
        key = redis_manager.make_key(_active_key(feature_key, user_id))
        val = await redis_manager.redis_client.get(key)
        if val:
            return val
    except Exception as exc:
        logger.warning(f"Redis get_active_task degraded, fallback PG: {exc}")

    # Redis 未命中或异常 → PG 降级查询
    # 注意：此处需要独立 session（因为可能在 Celery worker 中调用）
    try:
        from common.databases.PostgresManager import db_manager
        async with await db_manager.get_session() as db:
            stmt = (
                select(AiTask.celery_task_id)
                .where(
                    AiTask.user_id == user_id,
                    AiTask.feature_key == feature_key,
                    AiTask.status.in_(["pending", "processing"]),
                )
                .order_by(AiTask.created_at.desc())
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            return row
    except Exception as exc:
        logger.error(f"PG fallback for active task also failed: {exc}")
        return None


async def get_task_result(
    celery_task_id: str,
    db: AsyncSession = None,
) -> Optional[dict]:
    """
    获取任务结果（Redis-first → PG-fallback）。
    返回 dict: {status, result_data, error_message, ...} 或 None。
    """
    # 1. Redis 缓存
    try:
        key = redis_manager.make_key(_result_key(celery_task_id))
        cached = await redis_manager.redis_client.get(key)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        logger.warning(f"Redis get_task_result degraded: {exc}")

    # 2. PG 查询
    if db is None:
        from common.databases.PostgresManager import db_manager
        async with await db_manager.get_session() as db:
            return await _pg_get_task_result(db, celery_task_id)
    return await _pg_get_task_result(db, celery_task_id)


async def _pg_get_task_result(db: AsyncSession, celery_task_id: str) -> Optional[dict]:
    stmt = select(AiTask).where(AiTask.celery_task_id == celery_task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if not task:
        return None
    return {
        "celery_task_id": task.celery_task_id,
        "feature_key": task.feature_key,
        "status": task.status,
        "result_data": task.result_data,
        "error_message": task.error_message,
        "execution_time": task.execution_time,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


async def mark_completed(
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    result_data: str,
    started_at: float = None,
) -> None:
    """
    标记任务完成：更新 PG + 写 Redis 结果缓存 + 释放活跃锁。
    在 Celery worker 中调用，使用独立数据库 session。
    """
    execution_time = round(time.time() - started_at, 2) if started_at else None
    now = datetime.utcnow()

    # 1. PG 更新
    try:
        from common.databases.PostgresManager import db_manager
        async with await db_manager.get_session() as db:
            stmt = (
                update(AiTask)
                .where(AiTask.celery_task_id == celery_task_id)
                .values(
                    status="completed",
                    result_data=result_data,
                    execution_time=execution_time,
                    completed_at=now,
                )
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.error(f"mark_completed PG update failed: {exc}")

    # 2. Redis: 写结果缓存
    try:
        result_cache = json.dumps({
            "celery_task_id": celery_task_id,
            "feature_key": feature_key,
            "status": "completed",
            "result_data": result_data,
            "execution_time": execution_time,
            "completed_at": now.isoformat(),
        }, ensure_ascii=False)
        rkey = redis_manager.make_key(_result_key(celery_task_id))
        await redis_manager.redis_client.setex(rkey, RESULT_TTL, result_cache)
    except Exception as exc:
        logger.warning(f"Redis result cache write degraded: {exc}")

    # 3. Redis: 释放活跃锁
    try:
        lkey = redis_manager.make_key(_active_key(feature_key, user_id))
        await redis_manager.redis_client.delete(lkey)
    except Exception as exc:
        logger.warning(f"Redis release active lock degraded: {exc}")


async def mark_failed(
    user_id: int,
    feature_key: str,
    celery_task_id: str,
    error_message: str,
    started_at: float = None,
) -> None:
    """标记任务失败：更新 PG + 释放活跃锁。"""
    execution_time = round(time.time() - started_at, 2) if started_at else None

    # 1. PG 更新
    try:
        from common.databases.PostgresManager import db_manager
        async with await db_manager.get_session() as db:
            stmt = (
                update(AiTask)
                .where(AiTask.celery_task_id == celery_task_id)
                .values(
                    status="failed",
                    error_message=error_message,
                    execution_time=execution_time,
                    completed_at=datetime.utcnow(),
                )
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.error(f"mark_failed PG update failed: {exc}")

    # 2. Redis: 释放活跃锁
    try:
        lkey = redis_manager.make_key(_active_key(feature_key, user_id))
        await redis_manager.redis_client.delete(lkey)
    except Exception as exc:
        logger.warning(f"Redis release active lock degraded: {exc}")


async def get_user_history(
    db: AsyncSession,
    user_id: int,
    feature_key: str = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[AiTask], int]:
    """查询用户历史任务列表（PG 分页）。"""
    conditions = [AiTask.user_id == user_id]
    if feature_key:
        conditions.append(AiTask.feature_key == feature_key)

    # count
    count_stmt = select(func.count(AiTask.id)).where(*conditions)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # data
    stmt = (
        select(AiTask)
        .where(*conditions)
        .order_by(AiTask.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    return items, total
