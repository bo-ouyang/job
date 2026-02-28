@echo off
echo Starting Celery Worker (BATCH queue)...
set PYTHONPATH=%CD%
echo WorkDir: %CD%
:: Batch queue for background tasks (job parsing, ES sync, proxy)
:: Uses solo pool on Windows
celery -A worker.celery_app worker -Q batch --loglevel=info --pool=solo -n batch@%%h
pause
