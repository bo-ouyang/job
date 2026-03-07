from celery.signals import task_prerun, task_success, task_failure, worker_process_init, setup_logging
from common.databases.PostgresManager import db_manager
from crud.analysis import task_log
from crud import ai_task as crud_ai_task
from schemas.analysis_schema import TaskLogCreate, TaskLogUpdate
import asyncio
import json
import os
import logging

from core.logger import InterceptHandler, sys_logger as logger


@setup_logging.connect
def on_setup_logging(**kwargs):
    """Redirect Celery logs into Loguru sinks."""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    celery_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<magenta>Celery</magenta> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logging.getLogger().handlers = [InterceptHandler()]
    for logger_name in ("celery", "celery.worker", "celery.task", "celery.redirected"):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False

    logger.add(
        os.path.join(log_dir, "celery_app_{time:YYYY-MM-DD}.log"),
        format=celery_format,
        level="INFO",
        rotation="00:00",
        retention="3 days",
        enqueue=True,
        encoding="utf-8",
    )

    logger.add(
        os.path.join(log_dir, "celery_error_{time:YYYY-MM-DD}.log"),
        format=celery_format,
        level="ERROR",
        rotation="00:00",
        retention="3 days",
        enqueue=True,
        backtrace=True,
        diagnose=True,
        encoding="utf-8",
    )


def setup():
    """Explicit registration hint."""
    logger.info("Celery Events Module Loaded and Signals Connected")


def run_async(coro):
    """Run async code inside sync Celery signal handlers."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        asyncio.create_task(coro)
    else:
        loop.run_until_complete(coro)


@worker_process_init.connect
def init_worker_db(**kwargs):
    """Initialize DB in each worker process."""
    logger.info("Initializing DB for Worker Process...")
    run_async(db_manager.initialize())


@task_prerun.connect
def task_started_handler(task_id=None, task=None, args=None, kwargs=None, **other):
    """Record task started."""
    task_name = getattr(task, "name", "unknown_task")
    worker_name = getattr(getattr(task, "request", None), "hostname", "unknown_worker")
    logger.info(f"Task Started: {task_name} [{task_id}]")

    async def _log():
        try:
            async with db_manager.async_session() as db:
                try:
                    args_json = json.loads(json.dumps(args, default=str))
                except Exception:
                    args_json = str(args)

                try:
                    kwargs_json = json.loads(json.dumps(kwargs, default=str))
                except Exception:
                    kwargs_json = str(kwargs)

                obj_in = TaskLogCreate(
                    task_id=task_id,
                    task_name=task_name,
                    status="STARTED",
                    args=args_json,
                    kwargs=kwargs_json,
                    worker=worker_name,
                )
                await task_log.create(db, obj_in=obj_in)
                await db.commit()
        except Exception as exc:
            logger.error(f"Failed to log task start: {exc}")

    run_async(_log())


@task_success.connect
def task_success_handler(sender=None, result=None, **kwargs):
    """Record task success."""
    task_id = getattr(getattr(sender, "request", None), "id", None)
    sender_name = getattr(sender, "name", "unknown_task")
    worker_name = getattr(getattr(sender, "request", None), "hostname", "unknown_worker")
    logger.info(f"Task Success: {sender_name} [{task_id}]")

    async def _log():
        try:
            async with db_manager.async_session() as db:
                db_obj = await task_log.get_by_task_id(db, task_id=task_id)

                result_str = str(result)
                if len(result_str) > 5000:
                    result_str = result_str[:5000] + "..."

                if db_obj:
                    update_data = TaskLogUpdate(
                        status="SUCCESS",
                        result=result_str,
                    )
                    await task_log.update(db, db_obj=db_obj, obj_in=update_data)
                else:
                    obj_in = TaskLogCreate(
                        task_id=task_id,
                        task_name=sender_name,
                        status="SUCCESS",
                        result=result_str,
                        worker=worker_name,
                    )
                    await task_log.create(db, obj_in=obj_in)

                await db.commit()
        except Exception as exc:
            logger.error(f"Failed to log task success: {exc}")

    run_async(_log())


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, **other):
    """Record task failure and backfill AiTask failure status."""
    sender_name = getattr(sender, "name", "unknown_task")
    worker_name = getattr(getattr(sender, "request", None), "hostname", "unknown_worker")
    logger.info(f"Task Failure: {sender_name} [{task_id}]")

    async def _log():
        try:
            async with db_manager.async_session() as db:
                db_obj = await task_log.get_by_task_id(db, task_id=task_id)
                err_msg = f"{exception}\n{traceback}"

                if db_obj:
                    update_data = TaskLogUpdate(
                        status="FAILURE",
                        result=err_msg,
                    )
                    await task_log.update(db, db_obj=db_obj, obj_in=update_data)
                else:
                    try:
                        args_json = json.loads(json.dumps(args, default=str))
                        kwargs_json = json.loads(json.dumps(kwargs, default=str))
                    except Exception:
                        args_json, kwargs_json = str(args), str(kwargs)

                    obj_in = TaskLogCreate(
                        task_id=task_id,
                        task_name=sender_name,
                        status="FAILURE",
                        args=args_json,
                        kwargs=kwargs_json,
                        result=err_msg,
                        worker=worker_name,
                    )
                    await task_log.create(db, obj_in=obj_in)

                await db.commit()

                # If task crashes before entering task function body, fallback update AiTask.
                updated = await crud_ai_task.mark_failed_by_task_id(
                    celery_task_id=task_id,
                    error_message=err_msg,
                )
                if not updated:
                    logger.warning(f"AiTask not found while handling task failure: {task_id}")
        except Exception as exc:
            logger.error(f"Failed to log task failure: {exc}")

    run_async(_log())
