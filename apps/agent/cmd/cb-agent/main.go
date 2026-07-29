package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"circuitbreaker.dev/cb-agent/internal/capability"
	"circuitbreaker.dev/cb-agent/internal/config"
	"circuitbreaker.dev/cb-agent/internal/enroll"
	"circuitbreaker.dev/cb-agent/internal/link"
	"circuitbreaker.dev/cb-agent/internal/update"
)

// AgentVersion is overridden at build time via -ldflags "-X main.AgentVersion=1.2.3".
var AgentVersion = "0.0.0-dev"

func main() {
	if len(os.Args) < 2 {
		runDaemon()
		return
	}
	switch os.Args[1] {
	case "version":
		runVersion()
	case "status":
		runStatus()
	case "enroll":
		runEnroll()
	case "uninstall":
		runUninstall()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(1)
	}
}

func runDaemon() {
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
		fmt.Fprintf(os.Stderr, "cb-agent: enrollment: %v\n", err)
		os.Exit(1)
	}

	capGate := capability.New(config.StateDir())
	if err := capGate.LoadCached(); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
	}

	binaryPath, err := os.Executable()
	if err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
		os.Exit(1)
	}

	if pendingVersion, present, _ := update.ReadMarker(config.StateDir()); present {
		log.Printf("cb-agent: resuming after update to %s — watching for a successful link", pendingVersion)
		go func() {
			time.Sleep(2 * time.Minute)
			if v, stillPresent, _ := update.ReadMarker(config.StateDir()); stillPresent && v == pendingVersion {
				log.Printf("cb-agent: update to %s did not confirm within 2 minutes — rolling back", pendingVersion)
				if err := update.Rollback(binaryPath); err != nil {
					log.Printf("cb-agent: rollback failed: %v", err)
					return
				}
				update.ClearMarker(config.StateDir())
				syscall.Exec(binaryPath, os.Args, os.Environ()) //nolint:errcheck // best-effort re-exec after rollback
			}
		}()
	}

	var confirmOnce sync.Once
	onConnected := func() {
		confirmOnce.Do(func() {
			update.ClearMarker(config.StateDir())
		})
	}

	onUpdate := func(payload json.RawMessage) error {
		var instr update.Instruction
		if err := json.Unmarshal(payload, &instr); err != nil {
			return err
		}
		tmpPath, err := update.Download(cfg, instr)
		if err != nil {
			return err
		}
		if err := update.VerifySHA256(tmpPath, instr.SHA256); err != nil {
			os.Remove(tmpPath)
			return err
		}
		if _, err := update.Swap(tmpPath, binaryPath); err != nil {
			return err
		}
		if err := update.WriteMarker(config.StateDir(), instr.Version); err != nil {
			return err
		}
		log.Printf("cb-agent: updated to %s — re-executing", instr.Version)
		return syscall.Exec(binaryPath, os.Args, os.Environ())
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := link.Run(ctx, link.Options{
		Config: cfg, Key: key, AgentVersion: AgentVersion,
		OnCapabilitiesSet: capGate.ApplyGrants,
		OnUpdate:          onUpdate,
		OnConnected:       onConnected,
	}); err != nil && ctx.Err() == nil {
		fmt.Fprintf(os.Stderr, "cb-agent: %v\n", err)
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
	fmt.Println("link status: run without a subcommand to start the daemon")
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

func runUninstall() {
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

	if err := notifyUninstall(cfg, key); err != nil {
		fmt.Fprintf(os.Stderr, "cb-agent: could not notify server (continuing anyway): %v\n", err)
	}
	fmt.Println("Notified the server. Run as root to finish removal:")
	fmt.Println("  systemctl disable --now cb-agent")
	fmt.Println("  rm -f /etc/systemd/system/cb-agent.service /usr/local/bin/cb-agent")
	fmt.Println("  rm -rf /var/lib/cb-agent /etc/circuit-breaker")
}

func notifyUninstall(cfg *config.Config, key *enroll.DeviceKey) error {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return link.Uninstall(ctx, link.Options{Config: cfg, Key: key})
}
