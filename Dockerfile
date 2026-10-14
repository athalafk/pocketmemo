FROM python:3.11-slim

# System deps (curl for healthcheck; build essentials kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY pocketmemo/ ./pocketmemo/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Storage mount point for user files and exports
RUN mkdir -p /app/storage/files /app/storage/exports

EXPOSE 8001

# One worker: the Telegram Application must be a singleton.
CMD ["uvicorn", "pocketmemo.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
