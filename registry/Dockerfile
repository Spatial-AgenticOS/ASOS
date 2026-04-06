FROM python:3.12-slim
WORKDIR /app
COPY server.py seed.py ./
RUN pip install --no-cache-dir fastapi uvicorn pydantic
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
