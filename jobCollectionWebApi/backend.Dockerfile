FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/jobCollectionWebApi

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY jobCollectionWebApi/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/
COPY common/ /app/common/
COPY jobCollectionWebApi/ /app/jobCollectionWebApi/

EXPOSE 8000
