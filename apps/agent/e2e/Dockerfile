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
# Mirrors the real install script's versioned-symlink layout (Bug 1 fix,
# specs/2026-08-05-cb-agent-self-update-fix-design.md): the binary lands
# under /var/lib/cb-agent/versions/<version>/, owned by the unprivileged
# cb-agent user, and /usr/local/bin/cb-agent is a root-owned symlink chain
# through it — never a root-owned binary the daemon must rename in place.
# 0.0.0-dev matches AgentVersion's Go default (no -X ldflag is passed to
# this build) — the same "starts at the Go default" baseline
# test_agent_update_success_and_forced_rollback already relies on.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin cb-agent \
    && mkdir -p /etc/circuit-breaker \
    && mkdir -p /var/lib/cb-agent/versions/0.0.0-dev \
    && chown -R cb-agent:cb-agent /var/lib/cb-agent
COPY --from=build /cb-agent /var/lib/cb-agent/versions/0.0.0-dev/cb-agent
RUN chown cb-agent:cb-agent /var/lib/cb-agent/versions/0.0.0-dev/cb-agent \
    && chmod 0755 /var/lib/cb-agent/versions/0.0.0-dev/cb-agent \
    && ln -sfn versions/0.0.0-dev/cb-agent /var/lib/cb-agent/current \
    && chown -h cb-agent:cb-agent /var/lib/cb-agent/current \
    && ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent
USER cb-agent
ENTRYPOINT ["/usr/local/bin/cb-agent"]
