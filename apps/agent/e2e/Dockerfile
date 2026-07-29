FROM golang:1.22 AS build
WORKDIR /src
# Build context is apps/agent (set by the compose file's `build.context: ..`,
# relative to this Dockerfile's own directory) — COPY paths are relative to
# that context root, not to this Dockerfile's location, so `.` is correct
# here (not `..`, which Docker rejects as outside the build context).
COPY . .
RUN go build -o /cb-agent ./cmd/cb-agent

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /cb-agent /usr/local/bin/cb-agent
RUN useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent \
    && mkdir -p /etc/circuit-breaker /var/lib/cb-agent \
    && chown cb-agent:cb-agent /var/lib/cb-agent
USER cb-agent
ENTRYPOINT ["/usr/local/bin/cb-agent"]
