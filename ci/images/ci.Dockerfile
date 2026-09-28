# The one job image for Docker-runner jobs (plans/2026-09-28-gitlab-cutover.md).
# Built on the runner host's daemon by ci/gitlab/image.yml and never pushed:
# jobs use it with pull_policy if-not-present. Its tag is the first 12 hex of
# this file's sha256, and tests/build/test_gitlab_pipeline.py fails if the two
# disagree, so editing this file forces a rebuild.
FROM python:3.12-bookworm

ARG NODE_VERSION=20.20.2
ARG NODE_SHA256=df770b2a6f130ed8627c9782c988fda9669fa23898329a61a871e32f965e007d
ARG GO_VERSION=1.26.8
ARG GO_SHA256=d0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg jq make gcc git xz-utils sudo lsb-release; \
    install -d -m 0755 /etc/apt/keyrings; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/keyrings/pgdg.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/pgdg.gpg] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list; \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16 docker-ce-cli docker-compose-plugin; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"; \
    echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum --check --strict -; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1; \
    rm /tmp/node.tar.xz; \
    curl -fsSLo /tmp/go.tar.gz "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"; \
    echo "${GO_SHA256}  /tmp/go.tar.gz" | sha256sum --check --strict -; \
    tar -xzf /tmp/go.tar.gz -C /usr/local; \
    rm /tmp/go.tar.gz

ENV PATH="/usr/local/go/bin:/root/go/bin:${PATH}"
RUN node --version && go version && python3.12 --version && pg_dump --version && docker --version
