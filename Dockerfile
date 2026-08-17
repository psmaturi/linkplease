# ─── Build stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

# Don't write .pyc files; force stdout/stderr to be unbuffered (good for logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps needed to build asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Application layer ───────────────────────────────────────────────────────
COPY . .

RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Default: run the FastAPI app
CMD ["./start.sh"]
