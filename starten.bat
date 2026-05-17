@echo off
echo Stoppe alte Prozesse auf Port 5000...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":5000 " ^| findstr "ABHOREN LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 >nul
echo Starte Kalender...
cd /d "%~dp0"
start "" http://127.0.0.1:5000
python app.py
pause
