#!/usr/bin/env bash
# One-command start for macOS / Linux:  bash run.sh
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install --quiet -r requirements.txt
echo "EcoWise AI is starting at http://127.0.0.1:5000  (Ctrl+C to stop)"
python app.py
