@echo off
echo Starting Celery Beat Scheduler...
set PYTHONPATH=%CD%
echo WorkDir: %CD%
celery -A worker.celery_app beat --loglevel=info
pause
