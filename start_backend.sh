#!/bin/bash
echo "============================================"
echo "  Procure-AI Backend Server"
echo "============================================"
cd "$(dirname "$0")"
source .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null
export PYTHONPATH=.
echo "Starting FastAPI on http://localhost:5000 ..."
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 5000
