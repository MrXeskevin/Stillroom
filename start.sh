#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv || exit 1; fi
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
