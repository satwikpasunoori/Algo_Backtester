#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  ALGO MACHINE — start.sh
#  One-command launcher. Just run:  ./start.sh
# ─────────────────────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════╗"
echo "║         ALGO MACHINE — Docker Launcher           ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Check Docker is running ───────────────────────────────────
if ! docker info > /dev/null 2>&1; then
  echo -e "${RED}[ERROR] Docker is not running. Please start Docker Desktop first.${NC}"
  exit 1
fi

# ── Create .env if missing ────────────────────────────────────
if [ ! -f .env ]; then
  echo -e "${YELLOW}[SETUP] .env not found — creating from template...${NC}"
  cp .env.example .env
  echo -e "${YELLOW}[SETUP] Edit .env and add your Dhan credentials, then re-run this script.${NC}"
  echo -e "${YELLOW}        (Without credentials, synthetic data will be used for testing)${NC}"
fi

# ── Build & start ─────────────────────────────────────────────
echo -e "${GREEN}[BUILD] Building Docker image...${NC}"
docker compose build --no-cache

echo -e "${GREEN}[START] Starting Algo Machine...${NC}"
docker compose up -d

# ── Wait for health ───────────────────────────────────────────
echo -n "[WAIT] Waiting for server"
for i in {1..20}; do
  if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    echo ""
    break
  fi
  echo -n "."
  sleep 2
done

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✓  Algo Machine is RUNNING                      ║${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}║  Dashboard → http://localhost:8000               ║${NC}"
echo -e "${GREEN}║  API Docs  → http://localhost:8000/docs          ║${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}║  Logs:  docker compose logs -f                   ║${NC}"
echo -e "${GREEN}║  Stop:  docker compose down                      ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
