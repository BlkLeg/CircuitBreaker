VERSION ?= $(shell git -C .. describe --tags --always --dirty 2>/dev/null || echo 0.0.0-dev)
DIST ?= dist/$(VERSION)

# Base64 Ed25519 public key baked into the binary. The release job supplies
# the official one; an empty value (the default, and what `make
# build-from-source` produces) yields a warn-mode binary that still installs
# updates but cannot verify them. See internal/update/signature.go.
SIGNING_PUBKEY ?=

# The package path here is load-bearing: -X silently sets nothing when the
# path does not name a real package-level string variable, so a typo produces
# a binary that cannot verify anything and says so nowhere. `make
# verify-signing-key` is what catches that.
LDFLAGS = -X main.AgentVersion=$(VERSION) \
          -X circuitbreaker.dev/cb-agent/internal/update.SigningPublicKey=$(SIGNING_PUBKEY)

.PHONY: build-all manifest clean test verify-signing-key

build-all:
	mkdir -p $(DIST)
	GOOS=linux GOARCH=amd64 go build -ldflags "$(LDFLAGS)" \
		-o $(DIST)/cb-agent-linux-amd64 ./cmd/cb-agent
	GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS)" \
		-o $(DIST)/cb-agent-linux-arm64 ./cmd/cb-agent

# Proves the -X above actually reached the variable rather than silently
# doing nothing. Builds for the host so the result can be executed, then
# asks the binary itself what key it carries.
verify-signing-key:
	@test -n "$(SIGNING_PUBKEY)" || { echo "ERROR: set SIGNING_PUBKEY to the key to check"; exit 2; }
	@go build -ldflags "$(LDFLAGS)" -o /tmp/cb-agent-signing-check ./cmd/cb-agent
	@got=$$(/tmp/cb-agent-signing-check signing-key); \
	 rm -f /tmp/cb-agent-signing-check; \
	 test "$$got" = "$(SIGNING_PUBKEY)" || { \
	   echo "ERROR: embedded key is '$$got', expected '$(SIGNING_PUBKEY)'"; \
	   echo "The -X package path in LDFLAGS does not name the real variable."; \
	   exit 1; }
	@echo "signing key embedded correctly"

# -race is mandatory, not optional: the daemon-startup ordering defect this
# target exists to guard (cmd/cb-agent's startDaemonState) is only observable
# under the race detector — the non-race build passes with the bug present.
test:
	go test -race ./...

# The signing step imports `cryptography`, which lives in the project venv,
# not necessarily in whatever bare `python3` resolves to. A signing step that
# is silently skipped for a missing module is exactly the "the feature exists
# and has never run" defect this slice is written to prevent, so the
# interpreter is a variable the release path overrides.
PYTHON ?= python3

manifest: build-all
	$(PYTHON) scripts/gen_manifest.py $(DIST) $(VERSION)

clean:
	rm -rf dist
