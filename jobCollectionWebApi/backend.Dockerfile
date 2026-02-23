# Backend Dockerfile
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    pkg-config \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
# We assume requirements are in jobCollectionWebApi
COPY jobCollectionWebApi/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
# We copy the entire root context so we get common/, jobCollectionWebApi/, etc.
COPY . .

# Default command (can be overridden)
CMD ["python", "jobCollectionWebApi/main.py"]
