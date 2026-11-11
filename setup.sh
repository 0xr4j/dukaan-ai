#!/usr/bin/env bash
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install --no-deps paypal-agent-toolkit==1.11.0
[ -f .env ] || cp .env.example .env
echo "Setup done. Run: source .venv/bin/activate && uvicorn app.main:app --port 8000"
