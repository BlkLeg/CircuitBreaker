package logging

import (
	"bytes"
	"log"
	"strings"
	"testing"
)

func TestParseLevel_AcceptsTheDocumentedNames(t *testing.T) {
	for name, want := range map[string]Level{
		"debug": LevelDebug,
		"info":  LevelInfo,
		"warn":  LevelWarn,
		"error": LevelError,
		"DEBUG": LevelDebug,
		" Warn": LevelWarn,
	} {
		got, err := ParseLevel(name)
		if err != nil {
			t.Errorf("ParseLevel(%q) error = %v", name, err)
			continue
		}
		if got != want {
			t.Errorf("ParseLevel(%q) = %v, want %v", name, got, want)
		}
	}
}

func TestParseLevel_EmptyMeansTheDefault(t *testing.T) {
	got, err := ParseLevel("")
	if err != nil {
		t.Fatalf("ParseLevel(\"\") error = %v, want nil", err)
	}
	if got != LevelInfo {
		t.Errorf("ParseLevel(\"\") = %v, want LevelInfo", got)
	}
}

// A typo in agent.toml must be told to the operator, not silently ignored —
// which is what "log_level is parsed and never used" amounted to.
func TestParseLevel_RejectsAnUnknownName(t *testing.T) {
	_, err := ParseLevel("verbose")
	if err == nil {
		t.Fatal("ParseLevel(\"verbose\") = nil error, want a rejection")
	}
	if !strings.Contains(err.Error(), "verbose") {
		t.Errorf("error %q does not name the offending value", err)
	}
}

func TestWarnIsSuppressedBelowItsLevel(t *testing.T) {
	var buf bytes.Buffer
	restore := useForTest(&buf, LevelError)
	defer restore()

	Warnf("cb-agent: something odd")

	if buf.Len() != 0 {
		t.Errorf("Warnf emitted %q at log_level=error", buf.String())
	}
}

func TestErrorSurvivesTheQuietestLevel(t *testing.T) {
	var buf bytes.Buffer
	restore := useForTest(&buf, LevelError)
	defer restore()

	Errorf("cb-agent: enrollment failed: %v", "boom")

	if !strings.Contains(buf.String(), "enrollment failed: boom") {
		t.Errorf("Errorf output = %q, want the message at log_level=error", buf.String())
	}
}

func TestDebugIsSilentAtTheDefaultLevel(t *testing.T) {
	var buf bytes.Buffer
	restore := useForTest(&buf, LevelInfo)
	defer restore()

	Debugf("cb-agent: chatty detail")

	if buf.Len() != 0 {
		t.Errorf("Debugf emitted %q at log_level=info", buf.String())
	}
}

func TestDebugAppearsWhenAskedFor(t *testing.T) {
	var buf bytes.Buffer
	restore := useForTest(&buf, LevelDebug)
	defer restore()

	Debugf("cb-agent: chatty detail")

	if !strings.Contains(buf.String(), "chatty detail") {
		t.Errorf("Debugf output = %q, want the message at log_level=debug", buf.String())
	}
}

// The 60-odd existing log.Printf calls across the agent are informational and
// are not being reclassified one by one. Configure routes the standard log
// package through this level gate so they behave as Info — which is exactly
// what they do today at the default level, and correctly quiet at warn/error.
func TestConfigureRoutesTheStandardLogPackageThroughTheGate(t *testing.T) {
	var buf bytes.Buffer
	restore := useForTest(&buf, LevelInfo)
	defer restore()

	log.Printf("cb-agent: resuming after update to %s", "0.3.5")
	if !strings.Contains(buf.String(), "resuming after update to 0.3.5") {
		t.Fatalf("log.Printf output = %q, want it emitted at info", buf.String())
	}

	buf.Reset()
	SetLevel(LevelWarn)
	log.Printf("cb-agent: resuming after update to %s", "0.3.5")
	if buf.Len() != 0 {
		t.Errorf("log.Printf emitted %q at log_level=warn", buf.String())
	}
}

// The format the e2e suite greps must not change: plain message, one line, no
// key=value decoration.
func TestOutputKeepsThePlainSingleLineFormat(t *testing.T) {
	var buf bytes.Buffer
	restore := useForTest(&buf, LevelInfo)
	defer restore()

	Infof("cb-agent: updated to %s", "0.3.5")

	if got := buf.String(); got != "cb-agent: updated to 0.3.5\n" {
		t.Errorf("output = %q, want a bare message line", got)
	}
}
