@echo off
echo Starting Celery Worker...
set PYTHONPATH=%CD%
echo WorkDir: %CD%
:: Windows needs "solo" pool or simple "threads"
celery -A worker.celery_app worker --loglevel=info --pool=solo
pause
