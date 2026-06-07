@echo off
REM Musical Dynamics - dependency installer (Windows cmd).
REM Linux/macOS/WSL/Git Bash users: run ./setup.sh instead.
setlocal
cd /d "%~dp0"

echo == Musical Dynamics : setup ==

REM --- Python ---
set "PY="
where python >nul 2>&1 && set "PY=python"
if "%PY%"=="" ( where py >nul 2>&1 && set "PY=py" )
if "%PY%"=="" (
  echo [X] Python not found. Install from https://www.python.org/downloads/ and re-run.
  exit /b 1
)
echo - Python: & %PY% --version
%PY% -m pip install --upgrade pip
echo - Installing Python packages ^(numpy, mido, pillow^)...
%PY% -m pip install --upgrade numpy mido pillow

REM --- Node (optional, for the web app) ---
where npm >nul 2>&1
if %errorlevel%==0 (
  if exist web\package.json (
    echo - Installing web dependencies...
    pushd web & call npm install & popd
  ) else (
    echo - Skipping web deps ^(web\package.json not found^). index.html still works with no build.
  )
) else (
  echo - npm not found; skipping web deps. index.html still works with no build.
)

echo [OK] Setup complete.  Launch with:  run.bat
endlocal
