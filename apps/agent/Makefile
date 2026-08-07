VERSION ?= $(shell git -C .. describe --tags --always --dirty 2>/dev/null || echo 0.0.0-dev)
DIST ?= dist/$(VERSION)

.PHONY: build-all manifest clean test

build-all:
	mkdir -p $(DIST)
	GOOS=linux GOARCH=amd64 go build -ldflags "-X main.AgentVersion=$(VERSION)" \
		-o $(DIST)/cb-agent-linux-amd64 ./cmd/cb-agent
	GOOS=linux GOARCH=arm64 go build -ldflags "-X main.AgentVersion=$(VERSION)" \
		-o $(DIST)/cb-agent-linux-arm64 ./cmd/cb-agent

# -race is mandatory, not optional: the daemon-startup ordering defect this
# target exists to guard (cmd/cb-agent's startDaemonState) is only observable
# under the race detector — the non-race build passes with the bug present.
test:
	go test -race ./...

manifest: build-all
	python3 scripts/gen_manifest.py $(DIST) $(VERSION)

clean:
	rm -rf dist
