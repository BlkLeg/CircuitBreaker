package main

import (
	"fmt"
	"os"
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
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(1)
	}
}

func runVersion() {
	fmt.Printf("cb-agent %s\n", AgentVersion)
}
