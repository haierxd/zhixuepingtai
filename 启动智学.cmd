@echo off
pushd "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    echo Python environment is missing. See README.md for setup.
    pause
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m scripts.windows_launcher start %*
set "ZX_EXIT=%ERRORLEVEL%"
if not "%ZX_EXIT%"=="0" pause
popd
exit /b %ZX_EXIT%
