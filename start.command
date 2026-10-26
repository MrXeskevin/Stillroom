#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Creating local Python environment..."
  python3 -m venv .venv || { echo "Install Python 3.10+ and retry."; read -r; exit 1; }
fi
source .venv/bin/activate
if ! python -c 'import cv2, fastapi, multipart, uvicorn, PIL' >/dev/null 2>&1; then
  echo "Installing first-run dependencies (internet required only for this step)..."
  python -m pip install -r requirements.txt || { echo "Installation failed. Check internet/Python."; read -r; exit 1; }
fi
echo ""
echo "STILLROOM is available at http://127.0.0.1:8787"
(sleep 2 && (open 'http://127.0.0.1:8787' 2>/dev/null || true)) &
python app.py
