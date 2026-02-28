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

## Screenshots

### Login Screen
![Login Screen](screenshots/01-Login.png)

### Cluster-Centric Topology View
![Cluster-Centric Topology View](screenshots/01-cluster.png)

### Custom Layout Example
![Custom Layout Example](screenshots/01-custom-layout.png)

### Hardware Inventory Page
![Hardware Inventory Page](screenshots/01-hardware-page.png)

### Top-Down Topology Layout
![Top-Down Topology Layout](screenshots/01-top-down.png)

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

## Inspiration

Netbox was my first attempt at IPAM. I only have two quarrels with it as a first time user back then:

1. It was too complex to navigate quickly and consistently.
2. There was no visual aspect that represents my lab. In their defense, it took me quite some time to come to that realization for myself.

At the time, I also had a lesser understanding of various aspects of IT and server documentation in generation. There's a very good chance I could feel differently now. To each their own.

### Disclaimer

This app was vibe coded from the ground up with a twist. I spent a week in the planning phase, simply listing the features and workflow I wanted to see in Notion. Then, each phase of the program was designed and tested in phases. At no point was any large element of this app built in "one shot". To keep the code honest, I use a combination of Dependabot, SonarQube, Snyk, and sentry to monitor for CVEs and bugs. Before the deployment of the BETA, all crictical and high risk vulnerabilities were patched.

As we move closer to v1, the code itself will become increasingly optimized.