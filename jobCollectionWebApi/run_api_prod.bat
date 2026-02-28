@echo off
echo ========================================
echo  Starting FastAPI (PRODUCTION mode)
echo  Multi-worker + No reload
echo ========================================
set PYTHONPATH=%CD%
echo WorkDir: %CD%

:: Calculate workers: min(CPU_COUNT, 4) for Windows
:: Default to 4 workers on production
set WORKERS=4

echo Starting uvicorn with %WORKERS% workers...
uvicorn main:app --host 0.0.0.0 --port 8000 --workers %WORKERS% --log-config "" --no-access-log
pause
