@echo off
REM Musical Dynamics - run self-tests, serve the app, open a browser tab (Windows cmd).
REM Linux/macOS/WSL/Git Bash users: run ./run.sh instead.
setlocal
cd /d "%~dp0"

set "PY="
where python >nul 2>&1 && set "PY=python"
if "%PY%"=="" ( where py >nul 2>&1 && set "PY=py" )
if "%PY%"=="" ( echo [X] Python not found. & exit /b 1 )

echo == Musical Dynamics : run ==
echo - Reference self-tests:
%PY% mc_codec.py
%PY% -c "import pytest" 2>nul
if %errorlevel%==0 (
  echo.
  echo - Stego test suite:
  %PY% -m pytest tests/ -q
)

where npm >nul 2>&1
if %errorlevel%==0 if exist web\package.json (
  echo - Starting Vite dev server...
  start "" cmd /c "cd web ^&^& npm run dev"
  timeout /t 3 >nul
  start "" "http://localhost:5173"
  goto :eof
)

echo - Serving the single-file app at http://localhost:8000/index.html ^(close this window to stop^)...
start "" "http://localhost:8000/index.html"
%PY% -m http.server 8000
endlocal
