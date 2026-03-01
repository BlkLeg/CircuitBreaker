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

# Install build tools required by Pillow, httptools, and uvloop for arm64
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg-dev \
    zlib1g-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Layer 1: install only third-party deps (cached until pyproject.toml changes)
COPY backend/pyproject.toml ./
RUN python3 -c "\
import tomllib, subprocess, sys; \
data = tomllib.load(open('pyproject.toml', 'rb')); \
deps = data['project']['dependencies']; \
subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir'] + deps) \
"

# Layer 2: copy source and install the package itself (no re-download of deps)
COPY backend/app ./app
RUN pip install --no-cache-dir --no-deps .

# Copy built frontend assets from Stage 1
# Placed in /app/frontend/dist so FastAPI can serve them as static files
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Environment variables
ENV PYTHONPATH=/app/backend
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
CMD ["python", "app/start.py"]
