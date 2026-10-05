@echo off
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY="%USERPROFILE%\anaconda3\python.exe"
set PYW=pythonw
where pythonw >nul 2>nul || set PYW="%USERPROFILE%\anaconda3\pythonw.exe"
%PY% -c "import PyQt5, anthropic" 2>nul || %PY% -m pip install -r requirements.txt
if not exist .env copy .env.example .env >nul
start "" %PYW% -m spider
