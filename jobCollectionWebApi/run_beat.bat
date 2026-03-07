@echo off
echo Starting Celery Beat Scheduler...
set PYTHONPATH=%CD%
echo WorkDir: %CD%
:: Start real beat scheduler (not a worker queue)
celery -A worker.celery_app beat --loglevel=info --schedule=celerybeat-schedule
pause
