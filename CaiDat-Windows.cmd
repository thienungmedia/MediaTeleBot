@echo off
setlocal
cd /d "%~dp0"
where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >nul 2>nul
    if not errorlevel 1 (
        py -3 "%~dp0install_core.py" --gui
        if errorlevel 1 pause
        exit /b
    )
)
python -c "import sys, tkinter; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 (
    python "%~dp0install_core.py" --gui
    if errorlevel 1 pause
    exit /b
)
echo Cai Python 3.10 tro len co Tkinter tu https://www.python.org/downloads/windows/
pause
exit /b 1
