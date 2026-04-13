@echo off
echo ============================================
echo   Procure-AI Backend Server
echo ============================================
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set PYTHONPATH=.
echo Starting FastAPI on http://localhost:5000 ...
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 5000
