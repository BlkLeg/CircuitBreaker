VERSION ?= $(shell git -C .. describe --tags --always --dirty 2>/dev/null || echo 0.0.0-dev)
DIST ?= dist/$(VERSION)

.PHONY: build-all manifest clean

build-all:
	mkdir -p $(DIST)
	GOOS=linux GOARCH=amd64 go build -ldflags "-X main.AgentVersion=$(VERSION)" \
		-o $(DIST)/cb-agent-linux-amd64 ./cmd/cb-agent
	GOOS=linux GOARCH=arm64 go build -ldflags "-X main.AgentVersion=$(VERSION)" \
		-o $(DIST)/cb-agent-linux-arm64 ./cmd/cb-agent

manifest: build-all
	python3 scripts/gen_manifest.py $(DIST) $(VERSION)

clean:
	rm -rf dist
