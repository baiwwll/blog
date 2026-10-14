@echo off
cd /d "%~dp0"
if exist "%~dp0dist\EngineerHub\EngineerHub.exe" (
    start "" "%~dp0dist\EngineerHub\EngineerHub.exe"
) else (
    start "" pythonw.exe "%~dp0main.py"
)
