# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
# Install dependencies
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# Copy source and build
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend + Final Image
FROM python:3.12-slim
WORKDIR /app

# Install system dependencies if needed (e.g. for some python packages)
# RUN apt-get update && apt-get install -y --no-install-recommends ...

# Copy backend code
COPY backend /app/backend
WORKDIR /app/backend

# Install python dependencies from pyproject.toml
# We use pip to install the package in editable mode or just dependencies
RUN pip install --no-cache-dir .

# Copy built frontend assets from Stage 1
# We'll place them in /app/frontend/dist so FastAPI can serve them
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Environment variables
ENV STATIC_DIR=/app/frontend/dist
ENV DATABASE_URL=sqlite:////data/app.db
# Ensure the data directory exists
RUN mkdir -p /data

# Expose port (default 8080)
EXPOSE 8080

# Run commands
# We run uvicorn on 0.0.0.0:8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
