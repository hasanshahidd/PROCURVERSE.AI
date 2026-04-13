#!/bin/bash
echo "============================================"
echo "  Procure-AI Frontend Dev Server"
echo "============================================"
cd "$(dirname "$0")"
echo "Starting Vite on http://localhost:5173 ..."
npx vite --host
