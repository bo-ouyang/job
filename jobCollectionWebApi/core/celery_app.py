from celery import Celery
from jobCollectionWebApi.config import settings
import os

# Create Celery Instance
celery_app = Celery(
    "job_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "jobCollectionWebApi.tasks.resume_parser", 
        "jobCollectionWebApi.tasks.proxy_tasks",
        "jobCollectionWebApi.tasks.job_parser",
        "jobCollectionWebApi.tasks.es_sync",
        "jobCollectionWebApi.tasks.ai_tasks",
        "jobCollectionWebApi.tasks.ai_task_cleanup",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,

    # ── Queue routing ──────────────────────────────────
    task_default_queue="batch",  # Fallback queue for unrouted tasks
    task_routes={
        # Realtime queue — user-facing, latency-sensitive
        "parse_resume_task": {"queue": "realtime"},
        "tasks.ai_tasks.*": {"queue": "realtime"},

        # Batch queue — background, can tolerate delay
        "jobCollectionWebApi.tasks.job_parser.*": {"queue": "batch"},
        "jobCollectionWebApi.tasks.es_sync.*": {"queue": "batch"},
        "tasks.check_proxies": {"queue": "batch"},
        "tasks.fetch_proxies": {"queue": "batch"},
        "tasks.sync_proxies": {"queue": "batch"},
        "tasks.ai_task_cleanup.*": {"queue": "batch"},
    },

    # Schedule configuration (will adhere to Celery Beat)
    beat_schedule={
        'check-proxies-every-2-hours': {
            'task': 'tasks.check_proxies',
            'schedule': 7200.0, # 2 hours
        },
        'fetch-proxies-every-12-hours': {
            'task': 'tasks.fetch_proxies',
            'schedule': 3600*12, # 12 hours
        },
        'sync-proxies-every-12-hours': {
            'task': 'tasks.sync_proxies',
            'schedule': 3600*12, # 12 hours
        },
        'fetch-and-parse-jobs-every-1-minutes': {
            'task': 'jobCollectionWebApi.tasks.job_parser.process_job_parsing_task',
            'schedule': 60, # 每隔1分钟捞取一次
        },
        'cleanup-stale-ai-tasks-every-5-minutes': {
            'task': 'tasks.ai_task_cleanup.cleanup_stale_ai_tasks',
            'schedule': 300, # 每5分钟清理一次僵死AI任务
        },
    }
)
