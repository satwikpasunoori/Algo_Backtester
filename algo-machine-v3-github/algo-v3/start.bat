@echo off
REM ─────────────────────────────────────────────────────────────
REM  ALGO MACHINE v3 — start.bat
REM  Run this to deploy/update. It forces a clean rebuild.
REM ─────────────────────────────────────────────────────────────

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║         ALGO MACHINE v3 — Docker Launcher        ║
echo ╚══════════════════════════════════════════════════╝
echo.

REM Check Docker is running
docker info >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker Desktop is not running. Start it first.
    pause
    exit /b 1
)

REM Create .env if missing
IF NOT EXIST .env (
    echo [SETUP] .env not found - copying from template...
    copy .env.example .env
    echo [SETUP] Edit .env with your Dhan credentials then re-run.
    echo         Without credentials, synthetic data will be used.
    pause
)

echo [STOP] Stopping any running containers...
docker compose down

echo [BUILD] Building fresh image (no cache)...
docker compose build --no-cache

echo [START] Starting Algo Machine...
docker compose up -d

echo.
echo [WAIT] Waiting 12 seconds for server startup...
timeout /t 12 /nobreak >nul

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║  AlgoMachine v3 is RUNNING                       ║
echo ║                                                  ║
echo ║  Dashboard: http://localhost:8000                ║
echo ║  API Docs:  http://localhost:8000/docs           ║
echo ║                                                  ║
echo ║  Logs:  docker compose logs -f                   ║
echo ║  Stop:  docker compose down                      ║
echo ╚══════════════════════════════════════════════════╝
echo.
start http://localhost:8000
pause
