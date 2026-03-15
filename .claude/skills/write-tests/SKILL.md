***

## The File: `testing.SKILL.md`

````markdown
---
name: write-tests
description: >
  Writes proper tests that validate real code behavior. Use this skill when
  adding, reviewing, or fixing tests for any function, module, API route,
  or integration point. Applies to Go, TypeScript, React, Python, and Rust.
  This skill enforces real validation — no mock-heavy facades, no tests that
  only verify that mocks were called, no green tests that prove nothing.
---

# Testing Skill

## Core Philosophy

A test must fail when the code is wrong and pass when it is right.
If a test can pass while the feature is completely broken, it is not a test —
it is false confidence. Prefer fewer, honest tests over many hollow ones.

**The Three Laws of Useful Tests:**
1. A test that only verifies a mock was called proves nothing about behavior.
2. A passing test suite that misses real bugs is worse than no tests — it lies.
3. Tests are first-class code. Treat them with the same design discipline.

---

## Workflow

1. **Identify what to test** — Determine the observable behavior, not
   the implementation. Ask: "What should this code DO, not HOW does it do it?"

2. **Classify the test type:**
   - **Unit** — Pure logic with no IO; test in isolation with real inputs/outputs
   - **Integration** — Tests across two or more real components (DB, API, file)
   - **E2E** — Full system path from input to output; use sparingly, keep fast
   - **Regression** — Written to lock in a fixed bug; must reference the issue

3. **Write the test first** (TDD) when adding new logic.
   Write the test after only when hardening existing untested behavior.

4. **Structure every test as: Arrange → Act → Assert**
   No logic in the Assert block. Assert one behavior per test case.

5. **Name tests as sentences:**
   `TestCreateUser_ReturnsErrorOnDuplicateEmail` not `TestCreateUser2`

6. **Run and confirm it fails** before implementing the fix or feature.
   A test that was never red is a test of unknown value.

---

## Anti-Patterns — Never Do These

- **Mock the thing you're testing.** If you mock the service under test,
  you're testing nothing.
- **Assert only that a mock was called.** `expect(fn).toHaveBeenCalled()`
  without asserting the output is a facade [web:32].
- **Suppress errors silently.** Never `t.Skip()` or `_ = err` in test code
  without an explicit reason comment.
- **Test implementation details.** Don't assert on private fields, internal
  state, or call order unless that IS the contract.
- **Overload one test.** Each test case validates one behavior.
  A test that asserts 12 things is 12 tests pretending to be one.
- **Copy-paste test blocks.** Duplicate test setup = table-driven test waiting
  to be written.
- **Green tests in CI that never run locally.** All tests must be runnable
  with a single command, no manual steps, no environment assumptions.

---

## Language-Specific Rules

### Go
- Use **table-driven tests** as the default pattern [web:38]:
  ```go
  tests := []struct {
      name     string
      input    string
      expected string
      wantErr  bool
  }{
      {"empty input", "", "", true},
      {"valid input", "foo", "FOO", false},
  }
  for _, tt := range tests {
      t.Run(tt.name, func(t *testing.T) {
          got, err := MyFunc(tt.input)
          if (err != nil) != tt.wantErr {
              t.Fatalf("wantErr=%v, got err=%v", tt.wantErr, err)
          }
          if got != tt.expected {
              t.Errorf("got %q, want %q", got, tt.expected)
          }
      })
  }
  ```
- Run subtests in parallel where safe: `t.Parallel()` inside `t.Run`.
- Use `testify/assert` only for readability, never to suppress failures.
- For DB/IO: use `testing.T`-scoped temp dirs or real in-memory stores
  (e.g., SQLite, `pgx` with test containers) over mocks [web:32].
- Run with: `go test ./... -race -count=1`

### TypeScript / Vitest / Jest
- Use **table-driven** `.each()` for multi-case logic [web:36]:
  ```typescript
  it.each([
    ["empty string", "", null, true],
    ["valid slug", "hello-world", "hello-world", false],
  ])("%s", async (_, input, expected, shouldThrow) => {
    if (shouldThrow) {
      await expect(parseSlug(input)).rejects.toThrow();
    } else {
      expect(await parseSlug(input)).toBe(expected);
    }
  });
  ```
- Avoid `vi.mock()` at the module level for business logic tests.
  If you must mock, mock the interface boundary (HTTP client, DB adapter),
  never the logic layer itself.
- Use `msw` (Mock Service Worker) for HTTP boundary mocking over
  manual `fetch` mocks — it intercepts at the network level [web:37].
- Assert on rendered output, not component internals (no `instance()`,
  no private state access).
- Run with: `vitest run --reporter=verbose`

### React (Component Tests)
- Use `@testing-library/react`. Query by accessible role, label, or text —
  never by class name, test ID, or component name.
- Test what the user sees and does, not what props were passed.
- For async UI: use `waitFor` and `findBy*` queries, never `setTimeout`.
- Interaction pattern: render → act (userEvent) → assert (screen query).

### Python
- Use `pytest` with parametrize for table-driven patterns:
  ```python
  @pytest.mark.parametrize("input,expected", [
      ("", None),
      ("valid", "VALID"),
  ])
  def test_transform(input, expected):
      assert transform(input) == expected
  ```
- For DB tests, use `pytest-postgresql` or SQLite with real schema migrations.
- Never `assert True` or bare `except` in tests.
- Run with: `pytest -v --tb=short`

### Rust
- Use `#[cfg(test)]` modules co-located with source files for unit tests.
- Use `assert_eq!` and `assert_matches!` over custom boolean assertions.
- For error cases, use `assert!(result.is_err())` AND inspect the error variant.
- Run with: `cargo test -- --nocapture` for visibility.

---

## What Requires Real Integration Tests

Do not mock these — test them with real implementations:

| Component | Real Alternative to Mocking |
|---|---|
| SQL database | SQLite in-memory or Testcontainers (Postgres) |
| HTTP external API | `msw` (TS) or `httptest.NewServer` (Go) |
| File system | `os.TempDir()` / `t.TempDir()` scoped to test |
| Message queue | In-process channel (Go) or embedded broker |
| Auth/JWT | Real signing with test keys, not `vi.mock('jsonwebtoken')` |

---

## Output Format

When writing or reviewing tests, always output:

```
## Test File: <filename>
<complete test code>

## Coverage Intent
- What behavior this validates
- What it does NOT cover (be honest)
- Suggested follow-up test cases if any
```

---

## Constraints

- Never write a test that passes without asserting anything.
- Never use `toBeTruthy()` or `toBeDefined()` as the only assertion —
  assert the actual value.
- Never skip writing a `wantErr` case for functions that return errors.
- If a test requires more than 30 lines of setup, the code under test
  needs to be refactored first — flag this before writing the test.
- Do not write tests for framework internals (e.g., testing that
  React renders a div, that an ORM saves a field).
````

***
This skill file is designed to guide you in writing meaningful tests that validate real behavior, not just mock interactions. Follow the principles and patterns outlined here to ensure your tests provide true confidence in your code's correctness.