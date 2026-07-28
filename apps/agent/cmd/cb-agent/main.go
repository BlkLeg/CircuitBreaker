package main

import (
	"fmt"
	"os"

	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
)

// AgentVersion is overridden at build time via -ldflags "-X main.AgentVersion=1.2.3".
var AgentVersion = "0.0.0-dev"

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: cb-agent <status|enroll|version|uninstall>")
		os.Exit(1)
	}
	switch os.Args[1] {
	case "version":
		runVersion()
	case "status":
		runStatus()
	case "enroll":
		runEnroll()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(1)
	}
}

func runVersion() {
	fmt.Printf("cb-agent %s\n", AgentVersion)
}

func runStatus() {
	dir := config.StateDir()
	key, err := enroll.LoadOrCreateDeviceKey(dir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("fingerprint: %s\n", key.FingerprintGrouped())
	fmt.Println("link: not yet implemented (Task 11)")
}

func runEnroll() {
	cfg, err := config.Load("/etc/circuit-breaker/agent.toml")
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	key, err := enroll.LoadOrCreateDeviceKey(config.StateDir())
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
	if err := enroll.Run(cfg, key, AgentVersion); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}
}
