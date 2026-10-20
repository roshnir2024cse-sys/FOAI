@echo off
REM One-click start for Windows. Double-click this file.
cd /d "%~dp0"
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv || py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing requirements...
python -m pip install --quiet -r requirements.txt
echo.
echo EcoWise AI is starting at http://127.0.0.1:5000  (press Ctrl+C to stop)
start "" http://127.0.0.1:5000
python app.py
pause
