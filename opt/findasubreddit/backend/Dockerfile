FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080 \
    # trust X-Forwarded-* from proxy (Cloudflare/DO)
    FORWARDED_ALLOW_IPS="*"

WORKDIR /app

# System deps kept minimal
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Python deps (respect layer caching)
COPY requirements.txt /app/requirements.txt
RUN python -m pip install -U pip setuptools wheel \
 && pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir uvicorn[standard]

# App code only (no .env)
COPY src /app/src
COPY scripts /app/scripts

# Create non-root user
RUN useradd -r -u 10001 -g root appuser && chown -R appuser:root /app
USER appuser

# Local container healthcheck (DO uses its own)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8080}/health" || exit 1

EXPOSE 8080

# Use sh so ${PORT} expands; pass proxy header options
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8080", "src.api.app:app"]
