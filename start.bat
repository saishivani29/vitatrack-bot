@echo off
cd /d "D:\shivani software\vitatrack"
for /f "tokens=1,2 delims==" %%a in (.env) do set %%a=%%b
echo Starting VitaTrack bot...
echo Press Ctrl+C to stop.
venv\Scripts\python.exe vitatrack_bot.py
pause
