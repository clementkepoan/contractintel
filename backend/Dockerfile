# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/models/huggingface
ENV TRANSFORMERS_CACHE=/models/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/models/huggingface
ENV PYTHONPATH=/app

WORKDIR /app

# system deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-writer \
       libreoffice-core \
       default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# install CPU-only torch FIRST (CRITICAL). BuildKit cache keeps wheels for rebuilds.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch \
    --index-url https://download.pytorch.org/whl/cpu

# install rest of deps
COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

# copy app
COPY backend /app/backend
COPY Database /app/Database

# create dirs
RUN mkdir -p /models/huggingface /app/data /app/wiki

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
