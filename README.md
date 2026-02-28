# Circuit Breaker

> **⚠️ SECURITY WARNING (BETA RELEASE v0.1.0):**  
> This application is currently in beta. It has not yet undergone a full security audit. Please run this application strictly on a secure, local network (e.g., your homelab or a private intranet). **Do not expose it directly to the public internet.** Ensure you take your own precautions for securing the app and safeguarding your data until the full production release.

The **Circuit Breaker** (formerly Service Layout Mapper) is a tool designed to help you easily document, track, and visualize your homelab or small business network topology.

## Quick Start

The fastest and most reliable way to get started is using the pre-packaged Docker image.

```bash
# 1. Build the application image
docker build -t circuit-breaker .

# 2. Run the application
docker run --rm -p 8080:8080 -v $(pwd)/data:/data circuit-breaker
```

Once the container is running, open your web browser and navigate to:  
**http://localhost:8080**

## Documentation

For more information on using the tool and our upcoming plans, please refer to:

- [Architecture & Overview](docs/OVERVIEW.md)
- [Project Roadmap](docs/ROADMAP.md)

Build docs locally with Zensical:

```bash
source .venv/bin/activate
make docs-build
make docs
```
