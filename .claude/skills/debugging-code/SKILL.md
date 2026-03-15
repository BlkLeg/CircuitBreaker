Here is a production-ready `SKILL.md` for a Claude debugging skill, following Anthropic's official skill authoring best practices including proper YAML frontmatter, progressive disclosure, and workflow structure.

***

## The File: `debugging.SKILL.md`

```markdown
---
name: debugging-code
description: >
  Diagnoses and resolves bugs, errors, and unexpected behavior in code.
  Use this skill when the user reports a crash, unexpected output, failed test,
  runtime error, or wants root-cause analysis on broken functionality.
  Applies to Go, TypeScript, React, Python, Rust, Bash, and Docker environments.
---

# Debugging Skill

## Objective
Systematically identify root causes of bugs and deliver verified, minimal fixes
with clear explanation. Do not guess — reason from evidence.

## Workflow

1. **Triage** — Classify the issue type before doing anything else:
   - Runtime error / panic / crash
   - Logic error (wrong output, wrong behavior)
   - Build / compile error
   - Network / IO / environment error
   - Race condition / concurrency issue
   - Docker / container config error

2. **Gather Context** — Ask for or identify:
   - Exact error message and stack trace
   - Relevant code snippet(s)
   - Language, runtime version, and OS/container environment
   - Steps to reproduce
   - What changed recently (git diff, config change, dependency update)

3. **Hypothesize** — Form ranked hypotheses from most to least likely.
   State each hypothesis explicitly before investigating.

4. **Isolate** — Narrow scope to the smallest reproducible case.
   If unable to reproduce, explain why and request more context.

5. **Fix** — Propose the minimal correct fix. Do not refactor unrelated code.

6. **Verify** — Describe how to confirm the fix works:
   - Specific test command to run
   - Expected output/behavior after fix
   - Edge cases the fix must not break

7. **Explain** — Provide a concise root-cause summary in plain language.

---

## Language-Specific Rules

### Go
- Check for nil pointer dereferences, unchecked errors, and goroutine leaks.
- Use `fmt.Errorf("context: %w", err)` for error wrapping.
- Suggest `go vet`, `staticcheck`, or `golangci-lint` for static analysis.
- For race conditions, suggest re-running with `go test -race`.

### TypeScript / React
- Distinguish between type errors (compile-time) and runtime errors.
- Check for undefined/null prop access, stale closures in hooks, and
  missing dependency arrays in `useEffect`.
- Suggest `tsc --noEmit` to surface type errors without building.

### Python
- Identify IndentationError, NameError, and AttributeError origins.
- For async bugs, verify `await` usage and event loop context.
- Suggest `python -m pdb` or adding `breakpoint()` for live inspection.

### Rust
- Read the borrow checker error carefully — it usually identifies the fix.
- Check lifetime annotations, ownership transfers, and `unwrap()` panics.
- Suggest `RUST_BACKTRACE=1 cargo run` for full panic traces.

### Docker / Compose
- Check for port conflicts, missing env vars, volume mount issues, and
  network bridge misconfigurations.
- Suggest `docker logs <container>`, `docker inspect`, and
  `docker compose config` to validate resolved config.

### Bash / Shell
- Check for unquoted variables, incorrect exit code handling, and
  missing `set -euo pipefail`.

---

## Output Format

Structure every debug response as:

```
## Root Cause
<One sentence describing what went wrong and why>

## Fix
<Minimal code diff or corrected snippet>

## How to Verify
<Command or test to confirm resolution>

## Notes (optional)
<Edge cases, related risks, or follow-up recommendations>
```

---

## Constraints

- Never silently remove tests, error handling, or logging.
- Do not propose large refactors as a fix — scope to the bug only.
- If multiple root causes are plausible, list all before recommending one.
- When a fix requires an external dependency change, flag it explicitly.
- Always prefer deterministic, reproducible fixes over workarounds.
```

***
This `SKILL.md` provides a comprehensive, structured approach to debugging code across multiple languages and environments. It emphasizes evidence-based reasoning, minimal fixes, and clear communication of root causes and verification steps.