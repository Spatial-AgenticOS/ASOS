FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV THEORA_HOST=0.0.0.0
ENV THEORA_PORT=9090

WORKDIR /app

COPY . .

# Install dependencies deterministically for this image profile
RUN pip install --no-cache-dir ".[llm,sync]"

EXPOSE 9090

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('THEORA_PORT','9090')}/health\")" || exit 1

CMD ["python", "-m", "cli.main", "serve"]
