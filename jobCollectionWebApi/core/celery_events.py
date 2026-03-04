from celery.signals import task_prerun, task_postrun, task_success, task_failure, worker_process_init, setup_logging
from common.databases.PostgresManager import db_manager
from crud.analysis import task_log
from schemas.analysis_schema import TaskLogCreate, TaskLogUpdate
import asyncio
import json
import os
import sys
import logging
import time

from core.logger import InterceptHandler, sys_logger as logger

@setup_logging.connect
def on_setup_logging(**kwargs):
    """
    拦截 Celery (Worker 和 Beat) 的默认日志机制并导向 Loguru
    """
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 我们不在这一步 remove() sys.stdout 以免冲掉 WebAPI 的配置(如果同进程的话)
    # 但由于 Celery 是独立起进程 run_worker.bat，这里重新配一套针对 Celery 的存储
    
    celery_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<magenta>Celery</magenta> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # 为了防止控制台发两遍 (Celery自己会发)，我们干掉所有的 logging handler
    logging.getLogger().handlers = [InterceptHandler()]
    
    # 强制让常见的 Celery 日志流入 Loguru
    for logger_name in ("celery", "celery.worker", "celery.task", "celery.redirected"):
        logging_logger = logging.getLogger(logger_name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False
        
    # 添加专门给 Celery 定制的硬盘留存（3天限制）
    logger.add(
        os.path.join(log_dir, "celery_app_{time:YYYY-MM-DD}.log"),
        format=celery_format,
        level="INFO",
        rotation="00:00",
        retention="3 days", # 按照要求，仅保留三天
        enqueue=True,
        encoding="utf-8"
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
        encoding="utf-8"
    )


def setup():
    """Explicitly register signals (just by being imported, but this makes it visible)"""
    logger.info("Celery Events Module Loaded and Signals Connected")

# Helper to run async code in sync signals
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        # This shouldn't happen in standard prefork/solo worker signals, 
        # but if it does, we can't block.
        # However, signals usually run in main thread.
        # If loop is running, we might need create_task but that won't guarantee completion before return.
        # For logging, we want guaranteed completion.
        # If loop is running, we might be inside a coroutine task?
        # No, signals are called by Celery machinery independently.
        # For simplicity, we assume we can run_until_complete if not running.
        # If running, we just create task and hope.
        asyncio.create_task(coro)
    else:
        loop.run_until_complete(coro)

@worker_process_init.connect
def init_worker_db(**kwargs):
    """Worker 进程启动时初始化数据库"""
    logger.info("Initializing DB for Worker Process...")
    run_async(db_manager.initialize())

@task_prerun.connect
def task_started_handler(task_id=None, task=None, args=None, kwargs=None, **other):
    """任务开始"""
    logger.info(f"Task Started: {task.name} [{task_id}]")
    
    async def _log():
        try:
            async with db_manager.async_session() as db:
                # safe serialize
                try:
                    args_json = json.loads(json.dumps(args, default=str))
                except:
                    args_json = str(args)
                    
                try:
                    kwargs_json = json.loads(json.dumps(kwargs, default=str))
                except:
                    kwargs_json = str(kwargs)

                obj_in = TaskLogCreate(
                    task_id=task_id,
                    task_name=task.name,
                    status="STARTED",
                    args=args_json,
                    kwargs=kwargs_json,
                    worker=task.request.hostname
                )
                await task_log.create(db, obj_in=obj_in)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to log task start: {e}")

    run_async(_log())

@task_success.connect
def task_success_handler(sender=None, result=None, **kwargs):
    """任务成功"""
    task_id = sender.request.id
    logger.info(f"Task Success: {sender.name} [{task_id}]")
    
    async def _log():
        try:
            async with db_manager.async_session() as db:
                # Find log (assuming created in prerun)
                # If using rabbitmq/redis event loop, prerun might not have finished? 
                # But signals are sequential in same process usually.
                
                # Fetch existing
                db_obj = await task_log.get_by_task_id(db, task_id=task_id)
                
                result_str = str(result)
                if len(result_str) > 5000: result_str = result_str[:5000] + "..."
                
                # Calculate time?
                # db_obj.created_at is datetime.
                # execution_time = (now - created_at).total_seconds()
                
                if db_obj:
                    exec_time = None
                    if db_obj.created_at:
                        import datetime
                        # utc vs local? using func.now() usually matches python requests
                        # but safe way is just use time.time() if we stored start_time.
                        # For now, approximate
                        pass

                    update_data = TaskLogUpdate(
                        status="SUCCESS",
                        result=result_str
                    )
                    await task_log.update(db, db_obj=db_obj, obj_in=update_data)
                else:
                    # Fallback create
                    obj_in = TaskLogCreate(
                        task_id=task_id,
                        task_name=sender.name,
                        status="SUCCESS",
                        result=result_str,
                        worker=sender.request.hostname
                    )
                    await task_log.create(db, obj_in=obj_in)
                
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to log task success: {e}")
            
    run_async(_log())

@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, **other):
    """任务失败"""
    logger.info(f"Task Failure: {sender.name} [{task_id}]")
    
    async def _log():
        try:
            async with db_manager.async_session() as db:
                db_obj = await task_log.get_by_task_id(db, task_id=task_id)
                
                err_msg = f"{exception}\n{traceback}"
                
                if db_obj:
                    update_data = TaskLogUpdate(
                        status="FAILURE",
                        result=err_msg
                    )
                    await task_log.update(db, db_obj=db_obj, obj_in=update_data)
                else:
                    try:
                        args_json = json.loads(json.dumps(args, default=str))
                        kwargs_json = json.loads(json.dumps(kwargs, default=str))
                    except:
                        args_json, kwargs_json = str(args), str(kwargs)
                        
                    obj_in = TaskLogCreate(
                        task_id=task_id,
                        task_name=sender.name,
                        status="FAILURE",
                        args=args_json,
                        kwargs=kwargs_json,
                        result=err_msg,
                        worker=sender.request.hostname
                    )
                    await task_log.create(db, obj_in=obj_in)

                await db.commit()
        except Exception as e:
            logger.error(f"Failed to log task failure: {e}")
            
    run_async(_log())
