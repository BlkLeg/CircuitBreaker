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
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# --- Dependency layer (cached until requirements.txt changes) ---
# BuildKit cache mount keeps the wheel cache on the host between builds so
# subsequent runs are instant even when the network is unavailable.
# --timeout 120 --retries 5 guard against transient PyPI read timeouts.
COPY backend/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 5 -r requirements.txt

# --- App layer (invalidated only when source changes) ---
# VERSION must land at /VERSION so hatchling's path = "../VERSION" resolves.
COPY VERSION /VERSION
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /app/data /app/data/uploads/icons /app/data/uploads/branding

ENV PYTHONPATH=/app
ENV PORT=8000

EXPOSE 8000

CMD ["python", "app/start.py"]
