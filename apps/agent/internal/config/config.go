package config

import (
	"fmt"
	"os"

	"github.com/BurntSushi/toml"
)

type Config struct {
	ServerURL      string `toml:"server_url"`
	ServerStaticPK string `toml:"server_static_pk"`
	TLSPin         string `toml:"tls_pin"`
	LogLevel       string `toml:"log_level"`
	SpoolCapBytes  int64  `toml:"spool_cap_bytes"`
}

func Load(path string) (*Config, error) {
	var cfg Config
	if _, err := toml.DecodeFile(path, &cfg); err != nil {
		return nil, fmt.Errorf("config: load %s: %w", path, err)
	}
	return &cfg, nil
}

func StateDir() string {
	if dir := os.Getenv("CB_AGENT_STATE_DIR"); dir != "" {
		return dir
	}
	return "/var/lib/cb-agent"
}
