# Use a standardized, lightweight Linux image
FROM python:3.11-slim

# Prevent python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV POETRY_VERSION=1.7.1
ENV POETRY_VIRTUALENVS_CREATE=false

# Install Poetry
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app

# Copy dependency graphs first to cache the layer
COPY pyproject.toml poetry.lock* ./

# Install dependencies (without creating a virtualenv, directly to system)
RUN poetry install --no-root --no-interaction --no-ansi

# Copy the overarching brain logic
COPY . .

# Expose the WebSocket Brain port
EXPOSE 9090

# Run the API server
CMD ["python", "api/server.py"]
