# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Instafeed — production image
# Multi-stage: a slim runtime with only the packages the app actually needs.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Instafeed" \
      org.opencontainers.image.description="Your Instagram video feed, distilled." \
      org.opencontainers.image.source="https://github.com/Kumar44developer/instafed" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    INSTAFEED_DB_PATH=/data/instafeed.db \
    INSTAFEED_SCHEDULER=1

COPY --from=builder /opt/venv /opt/venv

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /usr/sbin/nologin instafeed \
 && mkdir -p /data \
 && chown -R instafeed:instafeed /data

WORKDIR /app
COPY --chown=instafeed:instafeed backend/ ./backend/
COPY --chown=instafeed:instafeed frontend/ ./frontend/
COPY --chown=instafeed:instafeed scripts/ ./scripts/

USER instafeed
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
