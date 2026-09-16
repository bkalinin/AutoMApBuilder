@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=UnityPy,PySide6-Essentials,shiboken6 -r requirements-gui.txt
pause
