# Stage 1: Build Frontend
FROM node:20.19.0-alpine3.21 AS frontend-builder
WORKDIR /app/frontend
# Install dependencies
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# Copy source and build — syncversion reads ../VERSION to stamp the bundle
COPY VERSION ../VERSION
COPY frontend/ ./
RUN npm run build

# Stage 2: Python dependency builder — includes gcc and build tools, excluded from runtime.
# Splitting into a separate stage sheds ~80-100 MB of compiler tooling from the final image.
FROM python:3.12.9-slim-bookworm AS python-builder
WORKDIR /app/backend

# Build tools needed for compiling C extensions on platforms without manylinux wheels
# (e.g. arm64/armv7). On amd64 all deps have prebuilt wheels — gcc/cargo are only
# exercised on ARM where source builds are necessary.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg-dev \
    zlib1g-dev \
    libffi-dev \
    libssl-dev \
    cargo \
    && rm -rf /var/lib/apt/lists/*

# --- Dependency layer (cached until requirements.txt changes) ---
# requirements.txt is generated from poetry.lock via: python3 scripts/gen_requirements.py
# Using a pinned file instead of resolving from pyproject.toml avoids PyPI read timeouts
# and makes the build fully deterministic.
COPY backend/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 5 -r requirements.txt

# --- App layer (invalidated only when source changes) ---
COPY VERSION ../VERSION
COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip install --no-cache-dir --no-deps .

# Stage 3: Runtime image — build tools stripped; final image only carries what runs.
FROM python:3.12.9-slim-bookworm
WORKDIR /app/backend

# Runtime-only deps: tini (init), wget (healthcheck), gosu (privilege drop).
# snmp / ipmitool: used by telemetry integration clients (SNMP polling, IPMI).
# No gcc — all compilation was done in python-builder above.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    wget \
    gosu \
    snmp \
    ipmitool \
    nmap \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Pull compiled packages and app code from the builder stage.
COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin
COPY --from=python-builder /app/backend/src ./src

# Copy built frontend assets from Stage 1
# Placed in /app/frontend/dist so FastAPI can serve them as static files
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Environment variables
ENV PYTHONPATH=/app/backend/src
ENV STATIC_DIR=/app/frontend/dist
ENV DATABASE_URL=sqlite:////data/app.db
ENV UPLOADS_DIR=/data/uploads
# Suppress .pyc writes (rootfs is read-only at runtime); ensure stdout/stderr are unbuffered.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Bake version into the image; overridable at `docker build` time via:
#   docker build --build-arg APP_VERSION=1.2.3 .
ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}
# APP_VERSION is read by pydantic-settings as settings.app_version at runtime.

# Create dedicated non-root user with a fixed UID (1000) for predictable bind-mount ownership.
# chown /app so the user can read the installed package; /data ownership is fixed at runtime
# by the entrypoint script (covers pre-existing volumes that were created as root).
RUN mkdir -p /data /data/uploads/icons /data/uploads/branding \
    && groupadd -g 1000 breaker26 \
    && useradd -u 1000 -g 1000 --no-create-home --shell /sbin/nologin breaker26 \
    && chown -R breaker26:breaker26 /app /data

# Copy entrypoint script that fixes /data ownership at startup and drops to breaker26 via gosu.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose port (default 8080)
EXPOSE 8080

# Health check — wget is available in this image (installed above).
# start-period=45s: covers the entrypoint chown + Python/uvicorn cold start on Pi 4 SD card
# (chown on a populated /data + uvicorn import chain can exceed 15s on arm64 slow storage).
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/api/v1/health || exit 1

# Container starts as root so that the entrypoint can fix /data volume ownership at runtime,
# then drops to breaker26 (UID 1000) via gosu before execing the app.
# tini as PID 1 ensures SIGTERM is forwarded to uvicorn and zombie processes are reaped.
# start.py is used instead of raw uvicorn to retain the AF_UNIX socketpair monkeypatch
# required for LXC/Proxmox container environments.
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
CMD ["python", "src/app/start.py"]
