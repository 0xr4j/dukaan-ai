@echo off
REM One-time setup on Windows
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install --no-deps paypal-agent-toolkit==1.11.0
if not exist .env copy .env.example .env
echo.
echo Setup done. Edit .env with your keys (optional), then run: run.bat
