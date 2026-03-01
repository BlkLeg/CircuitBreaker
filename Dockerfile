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
WORKDIR /app/backend

# Install Python dependencies first (layer is cached until pyproject.toml changes)
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application source (changes here do NOT invalidate the pip layer above)
COPY backend/app ./app

# Copy built frontend assets from Stage 1
# Placed in /app/frontend/dist so FastAPI can serve them as static files
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Environment variables
ENV STATIC_DIR=/app/frontend/dist
ENV DATABASE_URL=sqlite:////data/app.db
ENV UPLOADS_DIR=/data/uploads
# Ensure the data directory exists and create dedicated non-root user
RUN mkdir -p /data \
    && groupadd --system breaker26 \
    && useradd --system --gid breaker26 --no-create-home --shell /sbin/nologin breaker26 \
    && chown -R breaker26:breaker26 /app /data

# Expose port (default 8080)
EXPOSE 8080

# Run commands
# Keep root runtime for bind-mounted host /data compatibility in beta packaging checks.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
