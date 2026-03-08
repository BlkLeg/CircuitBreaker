# Development/compose backend image.
# Uses a pinned requirements.txt (generated from poetry.lock) so pip never
# resolves versions at build time, eliminating download-timeout flakiness.
#
# To regenerate requirements.txt after changing pyproject.toml dependencies:
#   python3 scripts/gen_requirements.py   (or: make lock)
FROM python:3.12-slim-bookworm

WORKDIR /app

# Runtime-only system packages — no compiler toolchain needed because all
# Python deps ship as manylinux binary wheels in requirements.txt.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    snmp \
    ipmitool \
    nmap \
    libpcap0.8 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# --- Dependency layer (cached until requirements.txt changes) ---
# BuildKit cache mount keeps the wheel cache on the host between builds so
# subsequent runs are instant even when the network is unavailable.
# --timeout 120 --retries 5 guard against transient PyPI read timeouts.
COPY apps/backend/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 5 -r requirements.txt

# --- App layer (invalidated only when source changes) ---
# VERSION must land at /VERSION so hatchling's path = "../VERSION" resolves.
COPY VERSION /VERSION
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

CMD ["python", "src/app/start.py"]
