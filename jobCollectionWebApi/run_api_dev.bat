@echo off
echo ========================================
echo  Starting FastAPI (DEV mode)
echo  Single worker + Auto-reload
echo ========================================
set PYTHONPATH=%CD%
echo WorkDir: %CD%
python main.py
pause
