@echo off
rem One-shot office bootstrap (Windows): venv + pinned deps + pheonix CLI + offline verification.
rem No uv required — plain python + pip only.
rem
rem Usage:
rem   scripts\office_setup.bat          offline analysis only
rem   scripts\office_setup.bat --live   also install the Phoenix client for live scraping
rem
rem Corporate proxy / mirror: set PIP_INDEX_URL / SSL_CERT_FILE / REQUESTS_CA_BUNDLE first.
setlocal enabledelayedexpansion
cd /d "%~dp0.."

set "REQS=requirements.txt"
if /i "%~1"=="--live" (
  set "REQS=requirements-live.txt"
) else if not "%~1"=="" (
  echo ERROR: unknown argument: %~1 ^(only --live is supported^)
  exit /b 2
)

set "PY="
for %%V in (3.14 3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY=py -%%V"
  )
)
if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo ERROR: no Python 3.11+ found ^(tried the py launcher and python^).
  echo Install Python 3.11+ from your software portal, then re-run.
  exit /b 1
)
echo Using %PY%

if not exist .venv (
  %PY% -m venv .venv
  if errorlevel 1 exit /b 1
)

rem An existing .venv may lack pip (uv-created venvs do) — bootstrap or rebuild it.
.venv\Scripts\python -m pip --version >nul 2>&1
if errorlevel 1 (
  echo Existing .venv has no working pip ^(created by uv?^) — bootstrapping with ensurepip.
  .venv\Scripts\python -m ensurepip --upgrade >nul 2>&1
  if errorlevel 1 (
    echo ensurepip failed — recreating .venv from scratch.
    rmdir /s /q .venv
    %PY% -m venv .venv
    if errorlevel 1 exit /b 1
  )
)

.venv\Scripts\python -m pip install -r %REQS%
if errorlevel 1 exit /b 1
.venv\Scripts\python -m pip install -e . --no-deps
if errorlevel 1 exit /b 1

echo.
echo Verifying the offline pipeline (no Phoenix connection needed)...
.venv\Scripts\pheonix demo
if errorlevel 1 exit /b 1

echo.
echo Setup complete. To scrape your live Phoenix instance:
echo   1. copy .env.example .env
echo   2. set PHOENIX_COLLECTOR_ENDPOINT ^(+ PHOENIX_API_KEY if your Phoenix has auth,
echo      and PHEONIX_PROJECT if your traces are not in "default"^)
echo   3. .venv\Scripts\pheonix scrape ^&^& .venv\Scripts\pheonix analyze ^&^& .venv\Scripts\pheonix report
endlocal
