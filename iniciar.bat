@echo off
REM RSL Automacao - inicia no Windows (duplo clique)
cd /d "%~dp0"
if not exist ".venv" (
  echo Preparando o ambiente pela primeira vez...
  py -3 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
".venv\Scripts\python.exe" app.py
pause
