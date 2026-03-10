# Development/compose backend image.
# Uses a pinned requirements.txt (generated from poetry.lock) so pip never
# resolves versions at build time, eliminating download-timeout flakiness.
#
# Multi-stage: deps are installed in a builder with gcc/libffi so that
# platforms without prebuilt wheels (e.g. linux/arm/v7) can build cffi/cryptography.
# To regenerate requirements.txt after changing pyproject.toml dependencies:
#   python3 scripts/gen_requirements.py   (or: make lock)

# --- Builder: install Python deps (needs gcc for armv7l and other source builds) ---
FROM python:3.12-slim-bookworm AS deps-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY apps/backend/requirements.txt apps/backend/requirements-pg.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 5 -r requirements.txt -r requirements-pg.txt --prefix /install

# --- Runtime: slim image, copy site-packages from builder ---
FROM python:3.12-slim-bookworm

WORKDIR /app

# Runtime-only system packages — no compiler toolchain.
# gosu: used by entrypoint to run app as non-root (breaker26).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    snmp \
    ipmitool \
    nmap \
    libpcap0.8 \
    postgresql-client \
    procps \
    libjpeg62-turbo \
    zlib1g \
    libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Create breaker26 user/group (matches entrypoint.sh and frontend image).
RUN groupadd -r breaker26 && useradd -r -g breaker26 -d /app -s /sbin/nologin breaker26

COPY --from=deps-builder /install /usr/local

# --- App layer (invalidated only when source changes) ---
# VERSION must land at /VERSION so hatchling's path = "../VERSION" resolves.
COPY VERSION /VERSION
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY apps/backend/pyproject.toml ./
COPY apps/backend/src ./src
COPY apps/backend/alembic.ini ./alembic.ini
COPY apps/backend/migrations ./migrations
RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /app/data /app/data/uploads/icons /app/data/uploads/branding

# Default logo embedded into the image so emails can attach it via CID
# without requiring an externally reachable URL (homelab installs are LAN-only).
COPY apps/frontend/public/CB-AZ_Final.png /app/default-logo.png

ENV PYTHONPATH=/app/src
ENV PORT=8000

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "src/app/start.py"]
