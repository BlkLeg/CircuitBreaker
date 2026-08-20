// Package logging gives `log_level` in /etc/circuit-breaker/agent.toml an
// effect.
//
// The setting was read into the config struct and used nowhere: the daemon
// logged unconditionally to standard error, so an operator who set
// log_level = "warn" got the same output as one who set "debug", and a typo
// was accepted in silence.
//
// Two deliberate choices here.
//
// The output format is a bare message line, identical to what `log.Printf`
// produced before. slog's TextHandler would have decorated every line with
// `time=... level=INFO msg=...`; systemd already stamps the journal, and the
// agent e2e suite greps this output, so the decoration would be cost with no
// benefit.
//
// Configure routes the standard `log` package through the same gate rather
// than reclassifying the ~60 existing `log.Printf` call sites. Those lines are
// informational and print unconditionally today, so Info is what they already
// are — this makes them quiet at warn/error without a mass edit whose only
// content would be one person's guess at each line's severity. Call sites that
// genuinely are errors use Errorf explicitly, so the quietest level still
// surfaces them.
package logging

import (
	"fmt"
	"io"
	"log"
	"os"
	"strings"
	"sync"
)

type Level int

const (
	LevelDebug Level = iota
	LevelInfo
	LevelWarn
	LevelError
)

func (l Level) String() string {
	switch l {
	case LevelDebug:
		return "debug"
	case LevelInfo:
		return "info"
	case LevelWarn:
		return "warn"
	case LevelError:
		return "error"
	}
	return fmt.Sprintf("Level(%d)", int(l))
}

var names = map[string]Level{
	"debug": LevelDebug,
	"info":  LevelInfo,
	"warn":  LevelWarn,
	"error": LevelError,
}

// ParseLevel maps a config value to a Level. An empty value is the default
// (info) — the setting is optional. Anything else that is not a known name is
// an error the caller is expected to surface: silently accepting it is the
// behaviour this package exists to remove.
func ParseLevel(value string) (Level, error) {
	trimmed := strings.ToLower(strings.TrimSpace(value))
	if trimmed == "" {
		return LevelInfo, nil
	}
	level, ok := names[trimmed]
	if !ok {
		return LevelInfo, fmt.Errorf(
			"unknown log_level %q (want one of: debug, info, warn, error)", value)
	}
	return level, nil
}

var (
	mu    sync.RWMutex
	level           = LevelInfo
	out   io.Writer = os.Stderr
)

// gate is the io.Writer the standard log package is pointed at: it forwards a
// record only when Info is enabled.
type gate struct{}

func (gate) Write(p []byte) (int, error) {
	mu.RLock()
	enabled := level <= LevelInfo
	writer := out
	mu.RUnlock()
	if !enabled {
		return len(p), nil
	}
	return writer.Write(p)
}

// Configure applies a config value, returning an error for an unknown name.
func Configure(value string) error {
	parsed, err := ParseLevel(value)
	if err != nil {
		return err
	}
	SetLevel(parsed)
	// No date/time prefix: journald stamps its own, and the plain line is
	// what the e2e suite greps.
	log.SetFlags(0)
	log.SetOutput(gate{})
	return nil
}

func SetLevel(l Level) {
	mu.Lock()
	level = l
	mu.Unlock()
}

func CurrentLevel() Level {
	mu.RLock()
	defer mu.RUnlock()
	return level
}

func emit(at Level, format string, args ...any) {
	mu.RLock()
	enabled := level <= at
	writer := out
	mu.RUnlock()
	if !enabled {
		return
	}
	message := fmt.Sprintf(format, args...)
	if !strings.HasSuffix(message, "\n") {
		message += "\n"
	}
	_, _ = io.WriteString(writer, message)
}

func Debugf(format string, args ...any) { emit(LevelDebug, format, args...) }
func Infof(format string, args ...any)  { emit(LevelInfo, format, args...) }
func Warnf(format string, args ...any)  { emit(LevelWarn, format, args...) }
func Errorf(format string, args ...any) { emit(LevelError, format, args...) }
