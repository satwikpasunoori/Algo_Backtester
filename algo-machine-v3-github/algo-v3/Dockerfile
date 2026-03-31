# ─────────────────────────────────────────────────────────────
#  ALGO MACHINE — Dockerfile
#  Multi-stage build for a lean, production-ready image
# ─────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ──────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for numpy/pandas compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime image ───────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="AlgoMachine"
LABEL description="Autonomous NSE strategy discovery & backtesting platform"

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security
RUN groupadd -r algomachine && useradd -r -g algomachine algomachine

# Copy project source (respects .dockerignore)
COPY --chown=algomachine:algomachine . .

# Persistent data directories — mounted as volumes at runtime
RUN mkdir -p /data/db /data/strategies && \
    chown -R algomachine:algomachine /data /app

# Switch to non-root user
USER algomachine

# Environment defaults (overridden by docker-compose env_file)
ENV DB_PATH=/data/db/algo_machine.db \
    OUTPUT_DIR=/data/strategies \
    PORT=8000 \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Healthcheck — pings the API every 30s
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["python", "run_server.py"]
