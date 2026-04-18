# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY feral_registry ./feral_registry
RUN pip install --prefix=/install "."

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FERAL_REGISTRY_BLOB_DIR=/data/blobs \
    FERAL_REGISTRY_DB_URL=sqlite+aiosqlite:////data/registry.db
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
WORKDIR /app
COPY feral_registry ./feral_registry
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN mkdir -p /data/blobs
EXPOSE 8080
CMD ["uvicorn", "feral_registry.main:app", "--host", "0.0.0.0", "--port", "8080"]
