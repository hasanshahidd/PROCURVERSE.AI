@echo off
echo ============================================
echo   Procure-AI Frontend Dev Server
echo ============================================
cd /d "%~dp0"
echo Starting Vite on http://localhost:5173 ...
npx vite --host
