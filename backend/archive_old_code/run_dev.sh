#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Building frontend..."
npm run build 2>/dev/null || npx vite build

echo "Starting Python backend..."
python -m uvicorn backend.main:app --host 0.0.0.0 --port 5000 --reload
