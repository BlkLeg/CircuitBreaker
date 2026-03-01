FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy metadata and source, then install
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir . \
    && mkdir -p /app/data

ENV PYTHONPATH=/app
ENV PORT=8000

EXPOSE 8000

CMD ["python", "app/start.py"]
