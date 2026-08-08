package discover

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// probePackage is the one package outside the standard library this collector may import, and
// probeAllowed is everything it may take from it.
//
// The allowlist is by *symbol* rather than by import path because probe is a single Go package:
// probe.ListenUnprivilegedICMP and probe.httpChecker live behind the same import, so forbidding
// the import would also forbid the ICMP socket Task 10 deliberately reuses.
//
// Every entry is a *host seam* — a question about this machine that both collectors have to ask
// and must not answer two different ways — and nothing else may be added without being one:
//
//   - EchoSession, ListenUnprivilegedICMP: the unprivileged datagram-ICMP socket the sweep and
//     probe's ICMP check both open (Task 10).
//   - SystemNameservers: /etc/resolv.conf. A second parser here could report discovery.dns ready
//     on a host where probe.dns is degraded, about one file.
//   - ICMPReadinessRemediation: the sysctl instruction for that same socket. Two wordings for one
//     kernel setting is two different answers to an operator holding one shell.
//
// What stays out is the whole checker layer — httpChecker, dnsChecker, the probe runtime and its
// result types. Discovery reports what it observed; it runs no monitor.
const probePackage = "circuitbreaker.dev/cb-agent/internal/collect/probe"

var probeAllowed = map[string]bool{
	"EchoSession":              true,
	"ListenUnprivilegedICMP":   true,
	"SystemNameservers":        true,
	"ICMPReadinessRemediation": true,
}

// forbiddenImports are the packages that would let discovery speak an application protocol.
//
// Plan §7: discovery follows no HTTP redirect and makes no application-level authenticated
// request. net/http does both by default — probe/http.go:297-303 installs a CheckRedirect that
// follows up to httpMaxRedirects hops, and http.Client carries an Authorization header or a
// cookie jar straight through them. Banner capture is a raw net.Conn read that writes nothing, so
// there is no legitimate reason for an HTTP client to appear in this package, and an import guard
// is the only assertion that keeps holding after the next contributor adds a collector.
var forbiddenImports = map[string]string{
	"net/http": "banner capture is a raw net.Conn read; plan §7 forbids following redirects or " +
		"making authenticated application-level requests",
	"golang.org/x/net/http2": "same reason as net/http",
	"os/exec": "plan §1 excludes bundling or invoking an external scanner; the neighbor cache is " +
		"read over netlink, not by shelling out to `ip neigh`",
}

// parsePackageSources parses every non-test source file of this package, build tags included.
//
// go/parser rather than the build package on purpose: `go build` for the host would skip
// neigh_stub.go entirely, and a forbidden import hiding behind //go:build !linux is exactly the
// one nobody would notice.
func parsePackageSources(t *testing.T) (*token.FileSet, map[string]*ast.File) {
	t.Helper()

	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatalf("read package directory: %v", err)
	}

	fset := token.NewFileSet()
	files := make(map[string]*ast.File)
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		parsed, err := parser.ParseFile(fset, filepath.Clean(name), nil, parser.SkipObjectResolution)
		if err != nil {
			t.Fatalf("parse %s: %v", name, err)
		}
		files[name] = parsed
	}

	// A filter typo that matched nothing would make every assertion below pass silently.
	if len(files) < 4 {
		t.Fatalf("parsed %d source files (%v); the package is larger than that", len(files), files)
	}
	return fset, files
}

func TestPackageImportsNoApplicationProtocolClient(t *testing.T) {
	fset, files := parsePackageSources(t)

	for name, file := range files {
		for _, spec := range file.Imports {
			path, err := strconv.Unquote(spec.Path.Value)
			if err != nil {
				t.Fatalf("%s: unquote import %s: %v", name, spec.Path.Value, err)
			}
			for forbidden, why := range forbiddenImports {
				if path == forbidden || strings.HasPrefix(path, forbidden+"/") {
					t.Errorf("%s imports %q: %s", fset.Position(spec.Pos()), path, why)
				}
			}
		}
	}
}

func TestPackageUsesOnlyTheHostSeamsOfProbe(t *testing.T) {
	fset, files := parsePackageSources(t)

	used := 0
	for name, file := range files {
		local := probeImportName(t, name, file)
		if local == "" {
			continue
		}
		ast.Inspect(file, func(node ast.Node) bool {
			selector, ok := node.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			qualifier, ok := selector.X.(*ast.Ident)
			if !ok || qualifier.Name != local {
				return true
			}
			used++
			if !probeAllowed[selector.Sel.Name] {
				t.Errorf("%s uses probe.%s; this package may take only the host seams %v from probe",
					fset.Position(selector.Pos()), selector.Sel.Name, sortedKeys(probeAllowed))
			}
			return true
		})
	}

	// Without this the allowlist would still pass on a package that stopped importing probe at
	// all, and the guard would be asserting nothing.
	if used == 0 {
		t.Fatal("no reference to the probe package found; the allowlist asserts nothing")
	}
}

func probeImportName(t *testing.T, file string, parsed *ast.File) string {
	t.Helper()
	for _, spec := range parsed.Imports {
		path, err := strconv.Unquote(spec.Path.Value)
		if err != nil {
			t.Fatalf("%s: unquote import %s: %v", file, spec.Path.Value, err)
		}
		if path != probePackage {
			continue
		}
		if spec.Name != nil {
			// A dot import would put every probe symbol in scope unqualified, past the selector
			// walk below.
			if spec.Name.Name == "." || spec.Name.Name == "_" {
				t.Fatalf("%s: %s must be imported under its own name", file, probePackage)
			}
			return spec.Name.Name
		}
		return "probe"
	}
	return ""
}

func sortedKeys(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for key := range set {
		out = append(out, key)
	}
	sort.Strings(out)
	return out
}
