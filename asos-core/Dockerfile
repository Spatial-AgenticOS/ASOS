FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./

# Install core deps + optional extras using pip (PEP 621)
RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir ".[llm,sync]" 2>/dev/null || true

COPY . .

EXPOSE 9090

CMD ["python", "api/server.py"]
