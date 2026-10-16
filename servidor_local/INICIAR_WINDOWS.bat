@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
echo.
echo Abre http://IP-DE-ESTE-EQUIPO:8765 en Android
echo Administracion: http://127.0.0.1:8765/admin
python -m uvicorn app:app --host 0.0.0.0 --port 8765
pause
