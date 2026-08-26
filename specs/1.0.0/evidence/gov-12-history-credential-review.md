# GOV-12 — git-history review of the removed `apps/agent/e2e/.env`

**Requirement:** GOV-12 — review/remove/relocate generated and user artifacts, and review git
history for credentials the removed files contained.
**Reviewer:** shawnji (governance)
**Review date:** 2026-08-26
**Scope of this document:** the second acceptance clause only. The first clause — the artifacts are
untracked and seven policy tests prevent recurrence by category — was already met and is asserted by
`tests/build/test_tracked_file_policy.py`. This document closes the history half, which the ledger
recorded as outstanding: *"git history was not reviewed for the test credentials the removed
`apps/agent/e2e/.env` contained, so they are still retrievable from earlier commits."*

## What was reviewed

`apps/agent/e2e/.env` was tracked from `82f467db` (`test(agents): end-to-end docker-compose
harness`) until `d3428099` (`chore(repo): remove tracked junk and user data`), with `781a1630`
completing the untracking. Its tracked content carried four secret-shaped values.

## Method

```
git log --all --oneline -S'<value>'          # every commit whose blob contains the value
git log --all --format='%H' -S'<value>' --name-only   # every path that ever contained it
grep -rF '<value>' . --exclude-dir=.git      # working-tree presence
```

Run per value rather than per file, so a value copied into a second file — a deployment template, a
docs example, a compose default — would surface even though the file it was copied *from* is the one
being retired. That is the failure mode a per-file review misses, and it is the reason the clause
was written.

## Findings

| Variable | Historical value | Assessment |
|---|---|---|
| `CB_DB_PASSWORD` | `e2e-test-password` | Self-describing placeholder. Not key material. |
| `CB_JWT_SECRET` | `e2e-test-jwt-secret-at-least-32-bytes-long` | Self-describing placeholder. Not key material. |
| `NATS_AUTH_TOKEN` | `e2e-test-nats-token-at-least-32-bytes-long` | Self-describing placeholder. Not key material. |
| `CB_VAULT_KEY` | `WudGoTcERDChnhiXzYKb3fOdxxpQDgac015DTVh1dZA=` | **Randomly generated 32-byte key.** Indistinguishable by inspection from production key material. |

Three of the four announce themselves as test values in the value itself. The fourth does not, and
is the only one this review treats as a credential.

### Blast radius of `CB_VAULT_KEY`

```
$ git log --all --oneline -S'WudGoTcERDChnhiXzYKb3fOdxxpQDgac015DTVh1dZA='
d3428099 chore(repo): remove tracked junk and user data, enforce a tracked-file policy (GOV-12)
82f467db test(agents): end-to-end docker-compose harness — enroll to online to revoke

$ git log --all --format='%H' -S'...' --name-only | sort -u
apps/agent/e2e/.env

$ grep -rF 'WudGoTcERDChnhiXzYKb3fOdxxpQDgac015DTVh1dZA=' . --exclude-dir=.git
(no matches)
```

- Introduced in exactly one commit, removed in exactly one commit.
- Present in exactly one path for its whole tracked life. It was never copied into a deployment
  template, a compose default, a documentation example, or a packaging file.
- Absent from the working tree.

### What the key could decrypt

Nothing that exists. The harness it belonged to pins `CB_DATA_DIR=./e2e-data`, and the comment
shipped alongside it records why: the root compose file resolves its volume path relative to its own
directory, so without the override the harness would share a real local deployment's database. The
override was deliberate isolation. The vault it keyed was a disposable per-run container volume,
created and destroyed by the e2e stack, and it never held anything but harness fixtures.

## Disposition

**No rotation is required, and no history rewrite is warranted.**

The value remains retrievable from `82f467db` and `d3428099` and always will be, short of rewriting
published history. That is accepted rather than remediated, on these grounds:

1. It keyed a self-isolating, per-run test vault whose data does not outlive the harness. There is
   no ciphertext anywhere that it opens.
2. It never reached any surface a deployment reads. The single-path result above is the evidence,
   not an assumption.
3. Rewriting history to remove it would invalidate every commit pin in this ledger — including the
   eight rows currently evidenced at `49b20ed1` — and would break the reproducibility the release
   control depends on. The cure is materially worse than the finding.

## Recurrence prevention

- `apps/agent/e2e/.env` is gitignored, and `.env.example` replaced it with placeholders that name
  themselves. Its `CB_VAULT_KEY` is now `UkVQTEFDRS1NRS1lMmUtdmF1bHQta2V5LTMyYnl0ZXM=`, which
  base64-decodes to the ASCII string `REPLACE-ME-e2e-vault-key-32bytes` — right shape, obviously not
  a key. That change is what stops the next harness author from committing a random one.
- `ensure_env.py` generates the working `.env` from the template, so no contributor has a reason to
  create one by hand.
- `tests/build/test_tracked_file_policy.py` fails the build if an env file is tracked again, by
  category rather than by filename.
- Gitleaks runs in the security workflow over the repository, so a newly committed secret is caught
  at the point it lands rather than at the next audit.
