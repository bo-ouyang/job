FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/jobCollectionWebApi

WORKDIR /app

ARG APT_MIRROR=https://mirrors.cloud.tencent.com/debian
ARG APT_SECURITY_MIRROR=https://mirrors.cloud.tencent.com/debian-security
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY jobCollectionWebApi/requirements.txt /tmp/requirements.txt
RUN pip install --index-url "$PIP_INDEX_URL" --upgrade pip \
    && pip install --index-url "$PIP_INDEX_URL" -r /tmp/requirements.txt

COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/
COPY common/ /app/common/
# Admin task generation imports shared task contracts from this package.
COPY jobCollection/ /app/jobCollection/
COPY jobCollectionWebApi/ /app/jobCollectionWebApi/

EXPOSE 8000
