@echo off
echo Starting Celery Worker (REALTIME queue)...
set PYTHONPATH=%CD%
echo WorkDir: %CD%
:: Realtime queue for user-facing tasks (resume parsing, etc.)
:: Uses solo pool on Windows
celery -A worker.celery_app worker -Q realtime --loglevel=info --pool=solo -n realtime@%%h --without-gossip --without-mingle
pause
