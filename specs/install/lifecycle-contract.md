# Lifecycle contract, version 1

Status: frozen by npm CLI sub-plan 03 Task 1 (`plans/2026-09-30-v0.4.7-npm-cli-03-lock-journal-events.md`).
It defines documents and rules only. It does not claim that any lifecycle command ships.
The [design](../../docs/design/2026-09-30-v0.4.7-npm-cli-design.md) is binding. The schemas below
implement it. Where this text and a schema disagree, the schema's tests fail.

| Document | Schema | Bound | Producer | Authority |
| --- | --- | --- | --- | --- |
| Execution plan | `packages/cli/schemas/lifecycle-plan.schema.json` | 64 KiB | coordinator (Node) | none: it describes, the native helper recomputes it |
| Event | `packages/cli/schemas/lifecycle-event.schema.json` | 4096 bytes per line | coordinator and native helper | none: presentation only |
| Result | `packages/cli/schemas/lifecycle-result.schema.json` | 256 KiB | the command that ran | the final statement of that run |
| Operation journal | `packages/cli/schemas/operation-journal.schema.json` | 64 KiB | native state utility, under the lock | authoritative lifecycle state |
| History index | `lifecycle-result.schema.json#/$defs/history_index` | 256 KiB | native state utility | derived from journals, never authoritative |

Each document carries its own `schema_version`. Each type versions on its own: a reader that
meets a version it does not read refuses the document as unsupported (exit 3). It never guesses.
Sub-plans 05–08 name the versions they consume. A change that would make a v1 reader accept
something different is a new version, never an edit to v1.

Validators: `packages/cli/src/lifecycle-contract.js` (coordinator) and the native state utility
`deploy/scripts/lifecycle-state.py` (sub-plan 03 Task 3, Python 3.9+ stdlib). Both interpret the
same schema subset, apply the numbered rules below, and pass the shared fixtures in
`packages/cli/test/fixtures/lifecycle/` (`valid.json`, `invalid.json`, `digest-vectors.json`,
`redaction-vectors.json`).
`tests/build/test_lifecycle_contract.py` pins the subset, the regex dialect, the canonical digest
in Python, and the tables in this file.

## 1. Encoding and shape (every document)

1. UTF-8 without a byte order mark. One JSON object at the top level.
2. The size bound applies to the bytes received, before parsing. In memory it applies to the
   canonical text (§2). **Bounds hold:** every member bound is chosen so that the largest
   document the schema and rules allow still fits its byte bound, counting 4 bytes per code
   point. A producer that writes only valid members can therefore always write the document.
   `packages/cli/test/lifecycle-contract.test.js` builds that largest document for each kind,
   and for the journal it searches every legal checkpoint sequence.
3. Object keys match `^[a-z][a-z0-9_]*$`. A key appears at most once. Nesting is at most 32 levels.
4. Numbers are safe integers. They are written `-?(0|[1-9][0-9]*)`, are not `-0`, and lie within
   ±(2^53−1). A fraction, an exponent or `-0` is refused even when its value is integral. A
   quantity that needs a fraction is carried as integer units (for example `duration_ms`).
5. Strings are well-formed Unicode: a lone surrogate is refused. `maxLength` counts code points.
6. Every object is closed (`additionalProperties: false`). A member that is not in the schema is
   refused. A refused member whose name looks like a secret (`password`, `token`,
   `vault_key`, …) is reported as a secret field.
7. Free text has no control characters except tab and newline: no C0 control, DEL, or C1
   control (U+0080–U+009F, which some terminals read as escape introducers), so it has no
   ANSI escapes. It must not have a credential shape: URL userinfo with a password, a PEM
   private key, `Bearer` tokens, or `password=`/`secret:`/`token=`/`api_key=`/`vault_key=`
   assignments. Three bounds, in code points:
   - `text`, 4096: result error reasons;
   - `message_text`, 900: event messages, so an event fits its 4096-byte line;
   - `brief_text`, 256: journal error reasons and evidence detail, plan presentation, history
     inspection reasons, so a journal, plan and index fit their bounds.

   **Redaction.** A producer passes every free-text value it writes through `redactText`
   (`lifecycle-contract.js`; the native utility implements the same steps and passes
   `redaction-vectors.json`). The steps, in order:
   1. A lone surrogate becomes U+FFFD.
   2. Each control character above (with `single_line`, tab and newline too) becomes the
      visible six-character text `\u00xx`, lowercase hex.
   3. Credential shapes are masked, repeating up to four rounds while one remains:
      - a PEM private key from `-----BEGIN … PRIVATE KEY-----` through its END line (or to the
        end of the text) → `[redacted private key]`;
      - URL userinfo `scheme://user:pass@` → `scheme://[redacted]@`;
      - `Bearer <token>` → `Bearer [redacted]`;
      - a secret assignment, the keyword kept and the value (one more `=`/`:` included) →
        `<keyword> (redacted)`.

      Text that still has a shape after four rounds becomes
      `[redacted: the text looked like it held a credential]`.
   4. Text over the bound keeps its first bound−1 code points and ends with `…` (U+2026).
      The ellipsis counts as a value character to the secret-assignment shape, so when the
      kept code points followed by `…` have a credential shape (the cut fell right after
      `token=`, `password: ` and the like), the trailing run of spaces, `=` and `:` is dropped
      from them before `…` is appended. Text from step 3 has no shape, so any shape the cut
      makes ends at the ellipsis, and dropping the separator in front of it removes it.

   The output always validates, so a producer's own words, including echoed user input, never
   make its document invalid. The validator's shape check is a backstop, not the redaction.
   Values a document reports exactly (paths, file names) are never redacted: a producer that
   cannot report one as it is refuses before using it (§7).

### Schema subset

Keywords: `$ref` (to `#/$defs/<name>` in the same file only), `type`, `const`, `enum`,
`format`, `pattern`, `minLength`, `maxLength`, `minimum`, `maximum`, `properties`, `required`,
`additionalProperties` (always `false`), `items`, `minItems`, `maxItems`, `uniqueItems`, `oneOf`,
`anyOf`, `not`. Annotations: `$schema`, `$id`, `title`, `description`, `$defs`, and members
starting with `x-`. Keyword semantics follow JSON Schema 2020-12. `const` and `enum` compare by
JSON type as well as by value: `true` is not `1`. `integer` means a safe integer.

Annotations that carry contract data:

- `x-max-bytes`: the bound above.
- `x-reason`: the message for a failed `pattern`.
- `x-fields`: the event members per type (§6).
- `x-lifecycle`: the state machine (§4).

Formats:

- `cb-utc-timestamp`: a real calendar date, hours ≤ 23, minutes and seconds ≤ 59. There is no
  leap second.
- `cb-operation-id`: the embedded date is a real calendar date.

Patterns are ECMAScript regular expressions in a dialect Python's `re` reads identically. They
use no `\d \w \s \b`, no named groups, no inline flags and no lookbehind. `$` appears only as an
anchor. Patterns are searched (JSON Schema semantics). Python validators compile each pattern
with `$` replaced by `\Z`, because Python's `$` also matches before a trailing newline.

### Identifiers

| Name | Form | Notes |
| --- | --- | --- |
| Operation ID | `op-YYYYMMDD-NNN` (`^op-[0-9]{8}-[0-9]{3,9}$`) | UTC date and a per-day counter of at least three digits. `begin` allocates it under the lock. Nothing builds a path from an ID that has not matched. |
| Digest | `sha256:` + 64 lowercase hex | plan, identity, artifact, manifest, scope and transition digests |
| Bundle SHA256 | 64 lowercase hex, no prefix | the landed `install --plan` result only |
| Key ID | 16 lowercase hex | `trust/release-bundle-keys.txt` |
| Release version | `X.Y.Z` or `X.Y.Z-pre`, no `v`, ≤ 64 | a release the coordinator resolved and verified: `$defs/version` |
| Installed version | 1–64 code points, no control character | a version as a host records it (`installed_version`): the install identity's `version` is free-form, and installers write `latest` or `unknown` today |
| Schema revision | `^[0-9A-Za-z_]{1,64}$` | an Alembic revision id |
| Path | absolute, normalized: no empty, `.` or `..` segment, no trailing `/`, no control character (C0, DEL, C1), ≤ 4096 | |
| Timestamp | RFC 3339 UTC with `Z`, optional 1–6 fractional digits | |
| Adapter | `native`, `mono`, `package`, `proxmox` | the install identity modes; Docker and Compose are transports of `mono` |

## 2. Canonical serialization and the plan digest

The canonical text of a document is UTF-8 JSON with:

- object keys sorted by code point;
- no insignificant whitespace;
- integers in shortest form;
- strings escaped as `JSON.stringify` does. That is `\"`, `\\`, `\b \f \n \r \t`, and other
  C0 controls as lowercase `\u00xx`. Nothing else is escaped: non-ASCII, DEL and U+2028 stay
  literal.

Node produces it with `canonicalize()`. Python produces the same bytes with
`json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")`.
It does so after rules 1.3–1.5 have been checked: ASCII keys and integer-only numbers are what
make the two agree without RFC 8785 number handling.

**Plan digest** = `sha256:` + hex SHA-256 of the canonical text of the plan with the top-level
`plan_digest` and `presentation` members removed. Every other member is bound. Volatile progress
never appears in a plan. Plan members that are not set are `null`, never absent, so a member's
absence cannot change the digest.

**Identity digest** = the same hash over the parsed install identity
(`specs/install/identity.schema.json`) as found on the host.

## 3. The execution plan

| Member | Meaning |
| --- | --- |
| `action` | `install`, `update`, `downgrade`, `rollback`, `recover`, `uninstall` |
| `adapter` | the lifecycle adapter, which is the install mode |
| `source` | the installed server: `version` (an installed version), `identity_digest`, `artifact_digest` (or null), `schema_revision` (or null); `null` for an install |
| `target` | the release to run: `version` (P9), `arch`, `channel` (or null), `artifact {name, digest}`, `schema_revision` (or null) |
| `compatibility` | `management` (`certified`, `uncertified`, `not_applicable`), `schema` (`none`, `forward`, `compatible`, `incompatible`), `transition_digest` of the signed certification that allows it (or null) |
| `options` | installer options forwarded verbatim: `port`, `fqdn`, `cert_type`, `email`, `data_dir`, `tls`, `docker`, `airgap`; `null` when no installer runs |
| `downtime` | `none`, `restart`, `outage` |
| `recovery` | `mode` (`none`, `new_point`, `existing_point`) and `ref {operation_id, manifest_digest}` |
| `data` | `effect` (`none`, `retained`, `migrated`, `restored`, `removed`), `restore_point_at` (the restored point's time, so newer writes are known lost), `scope_digest` (sub-plan 07's removal scope) |
| `trust` | `signature` (`{key_id}` or `{unsigned: pinned or explicit-older}`) and `provenance` (`verified`, `skipped-airgap`, `not-applicable`), exactly as `install --plan` reports them |
| `acknowledgments` | the acknowledgments execution requires: `confirm`, `restore_data`, `purge` |
| `presentation` | optional display text (`summary`, up to 32 `lines`, each brief text), outside the digest |
| `plan_digest` | optional; when present it must equal the computed digest |

Rules:

- **P1** A present `plan_digest` equals the computed digest.
- **P2** `source` is null exactly for `install`.
- **P3** `target` is null exactly for `uninstall` and `recover`.
- **P4** `install`, `update` and `downgrade` carry `trust`. A plan without a target carries none.
- **P5** `recovery.ref` is set exactly when `mode` is `existing_point`. An install's mode is
  `none`, and a rollback's is `existing_point`.
- **P6** `management` is `not_applicable` exactly when there is no source.
- **P7** `restore_point_at` is set exactly when data is `restored`. `scope_digest` is set exactly
  for `uninstall`.
- **P8** `acknowledgments` always include `confirm`. They include `restore_data` exactly when data
  is restored, and `purge` exactly when data is removed.
- **P9** The target of an `install`, `update` or `downgrade` is a resolved release, so its
  `version` is a release version. A `rollback` targets a recovery point's release, which carries
  the installed version that host recorded (for example `latest`).
- **P10** The source version is the install identity's `version` as found. `identity_digest`
  binds the whole identity whatever the version says. When that version is not an installed
  version (a control character, or over 64 code points), the coordinator refuses with
  `UNSUPPORTED` before planning and names the identity file to repair. It never invents or
  rewrites a version.

## 4. Operation states and transitions

Eleven states: `planned`, `staged`, `verified`, `recovery_saved`, `applying`, `checking`,
`committed`, `recovering`, `recovered`, `recovery_required` and `interrupted`. The states before
mutation are `planned`, `staged`, `verified` and `recovery_saved`. `applying` is the first
mutation checkpoint.

There are two kinds of operation:

- **transaction**: the orchestrated path from sub-plan 05 on.
- **legacy**: a direct shell command (install.sh, `cb update`, restore.sh, `cb migrate upgrade`,
  …) recording its actual smaller scope. A legacy record never claims `verified` or
  `recovery_saved`.

<!-- lifecycle-transitions:begin -->
| From | Transaction may go to | Legacy may go to |
| --- | --- | --- |
| (start) | planned | applying |
| planned | staged, interrupted | — |
| staged | verified, interrupted | — |
| verified | recovery_saved, applying, interrupted | — |
| recovery_saved | applying, interrupted | — |
| applying | checking, recovering, recovery_required, interrupted | committed, recovery_required, interrupted |
| checking | committed, recovering, recovery_required, interrupted | — |
| committed | — | — |
| recovering | recovered, recovery_required, interrupted | — |
| recovered | — | — |
| recovery_required | recovering | — |
| interrupted | recovering, recovery_required | — |
<!-- lifecycle-transitions:end -->

A journal is one document per operation. It is atomically replaced at each durable checkpoint,
and `generation` counts those writes. `checkpoints` lists the states the operation passed through,
in order. Each entry has a `sequence`, which is drawn from the same per-operation counter as its
events (§6). Rules:

- **J1** The first checkpoint is `planned` for a transaction and `applying` for a legacy record.
- **J2** A transaction binds `plan_digest`. A legacy record's `plan_digest` is null.
  `generation` is never below the number of checkpoints.
- **J3** A repeated state is allowed only as mutation progress: the same `applying`, `checking` or
  `recovering` with a `step` (`^[a-z][a-z0-9_]{0,63}$`), following a record of that state
  without one. A run of one state therefore has at most two records: as the step advances,
  the state utility replaces the stepped record in place (new `sequence`, new `generation`)
  instead of appending. The other exceptions are the closing records of J6 (`refused`,
  `manual`). Otherwise each step follows the table.
- **J4** `verified → applying` skips the recovery point. Only an `install`, which has nothing to
  recover, may take it.
- **J5** `interrupted` and `recovery_required` records carry a `cause`, and no other record does.
  The causes are:
  - `interrupted`: an INT/TERM trap ran.
  - `abandoned`: the next lock holder found the operation unfinished and its process gone.
  - `apply_failed`, `check_failed`, `recovery_failed`.

  `recovery_required` takes `interrupted`, `apply_failed`, `check_failed` or `recovery_failed`.
  `interrupted` takes `interrupted` or `abandoned` when its checkpoint is before mutation, and
  only `abandoned` when its checkpoint is a mutation state: after mutation a trap records
  `recovery_required` with cause `interrupted`, so only a killed process (no trap ran) leaves
  an `interrupted` record there.
- **J6** `outcome` closes an operation. It appears only on the last record, and nothing follows
  it.
  - `committed` and `recovered` are exactly the records in those states.
  - `refused` closes a failure before mutation. It is written on a record that repeats the last
    pre-mutation state. No new state is added.
  - `interrupted` closes an `interrupted` record whose checkpoint is before mutation, and every
    such record carries it, whatever its cause. Nothing changed, so a trap's record and the
    next lock holder's `abandoned` record for a process killed while staging both finish the
    operation: it never blocks a `begin`, and `recovering` or `recovery_required` can follow an
    `interrupted` record only from a mutation checkpoint.
  - `manual` closes a `recovery_required` operation on a record that repeats it (same cause and
    error). The state utility writes it only on an explicit operator acknowledgment that the
    host was resolved by hand (sub-plan 06), never on its own. It is not a success: history
    shows it as `manual`.
- **J7** An `interrupted` record names in `checkpoint` the state of the record before it: the last
  durable checkpoint, which it preserves.
- **J8** Errors:
  - Refused, `recovered` and `recovery_required` records carry an `error`. An `interrupted`
    record may carry one. No other record does.
  - Codes follow §5. `recovery_required` uses `INTERRUPTED` exactly when its cause is
    `interrupted`.
- **J9** Sequences increase. Once a `recovery_saved` record exists, `recovery` references the
  point.
- **J10** An operation makes at most 3 recovery attempts (`x-lifecycle.max_recovery_attempts`): a
  run of `recovering` records is one attempt. After the last failed attempt the operation stays
  `recovery_required` (exit 9, manual intervention) until a `manual` record closes it. With J3,
  this bounds every legal journal: the longest has 23 records, within `maxItems` 32, and its
  worst-case filling (16 evidence entries, every reason at 256 four-byte code points) fits
  64 KiB. No legal journal can reach a state with no legal way to finish.
- **J11** `source` and `target` carry installed versions, or are null when not known. A
  `transaction` whose action is `install`, `update` or `downgrade` targets a release version
  (P9). A legacy producer whose version is not an installed version records that member as
  null.

**Finished** means the last record has an `outcome`. An unfinished record is one of these:

- an operation in progress;
- `recovery_required`;
- an `interrupted` record whose last durable checkpoint is a mutation state (cause
  `abandoned`).

Unfinished records await reconciliation by `recover` (sub-plan 06).

What happens on interruption:

- INT or TERM before the first mutation checkpoint records `interrupted`, closed with outcome
  `interrupted`, and exits 130.
- INT or TERM after it records `recovery_required` with cause `interrupted`, and exits 130.
- A killed process runs no trap. History reports its unfinished record as `interrupted`, and the
  next lock holder persists that with cause `abandoned`. The record keeps the last durable
  checkpoint. Killed before mutation, the record is closed with outcome `interrupted` like a
  trapped one; killed after it, the record stays unfinished for `recover`.

In sub-plan 03, only an unfinished `transaction` blocks a new `begin` (exit 9). An unfinished
legacy record is reported, and the next `begin` names it as a warning, but it does not block.

## 5. Exit codes

<!-- lifecycle-exit-codes:begin -->
| Code | Name | Meaning |
| --- | --- | --- |
| 0 | OK | success, or no change |
| 2 | USAGE | invalid usage |
| 3 | UNSUPPORTED | unsupported platform, mode, compatibility or document version |
| 4 | NETWORK | network failure |
| 5 | TRUST | trust verification failed |
| 6 | PERMISSION | permission denied |
| 7 | PREFLIGHT | backup or preflight failed |
| 8 | RECOVERED | activation failed but was recovered |
| 9 | MANUAL | recovery failed or needs manual intervention; an unfinished transaction blocks |
| 10 | LOCKED | another lifecycle operation holds the host lock |
| 130 | INTERRUPTED | interrupted |
<!-- lifecycle-exit-codes:end -->

These are the CLI's own decisions (`packages/cli/src/exit-codes.js`). Forwarded native management
commands (passthrough) keep their own exit codes and output unchanged. No lifecycle code ever
replaces a child's status. A result's exit code is that of its `error.code`, or 0 without an
error (`exitCodeFor`).

## 6. Events

An event is one JSON object on one line, at most 4096 bytes before its `\n`. The envelope
is `schema_version`, `operation_id`, `sequence`, `at`, `source` (`coordinator` or `native`) and
`type`. The per-type members are listed in the schema's `x-fields`:

| `type` | Members | Meaning |
| --- | --- | --- |
| `phase` | `phase`, `status`, optional `duration_ms` (completed or failed only) | a phase started, completed, failed or was skipped |
| `progress` | `phase`, `done`, `total` (null when unknown; otherwise `done ≤ total`), `unit` (`bytes`, `steps`) | measured units only, never a fabricated percentage |
| `checkpoint` | `state`, `generation` | emitted by the native side only, after the journal write is durable |
| `diagnostic` | `level`, `message` (at most 900 code points), optional `code` | a redacted diagnostic that would otherwise be unframed stderr; a longer one is cut by redaction, and the final result carries it whole |

The phases are `preflight`, `resolve`, `download`, `verify`, `stage`, `backup`, `stop`, `apply`,
`migrate`, `start`, `health`, `commit`, `recover`, `remove` and `cleanup`.

Rules:

- **E1** Members not listed for the type are refused.
- **E2** Native events, and every `checkpoint`, name their operation. Coordinator events before
  an operation exists (planning) carry `operation_id: null`.
- **E3** `sequence` strictly increases per (`source`, `operation_id`). A consumer drops an event
  that does not. The native sequence is allocated under the lock from a counter in the
  operation's private directory. After a restart it continues above the journal's durable
  sequence, so nested native processes share one sequence.
- **E4** An event never authorizes, changes or proves state, including an out-of-order or invalid
  one. Only the journal is authoritative. No later plan may treat a progress event as mutation
  authority.

**Native event descriptor.**

- The native helper writes events only to the inherited descriptor named by
  `CB_LIFECYCLE_EVENT_FD`, after validating it. It never writes them to its stdout or stderr.
- Without that descriptor it emits no events, and standalone shell keeps its own renderer.
- The coordinator reads the descriptor in bounded chunks and reassembles lines across partial
  reads. It validates every line and refuses any over the bound.
- The descriptor travels with the lock handoff (`CB_LIFECYCLE_LOCK_FD`, `CB_LIFECYCLE_OPERATION`).
  A claim in the environment alone grants nothing.

## 7. Results and output streams

`--json` prints exactly one result object on stdout, followed by `\n`. Nothing else goes to
stdout. What each outcome carries:

| `outcome` | `plan` | `error` (code) | operation members | plan members | `operations` |
| --- | --- | --- | --- | --- | --- |
| `verified` | `true` | — | optional, `operation_id` null | required | — |
| `refused` | `true` or absent | required (not `RECOVERED`/`INTERRUPTED`) | required unless a plan or history | — | — |
| `available` | absent | — | required, `operation_id` null, `target_version` set | — | — |
| `no_change` | absent | — | required | — | — |
| `committed` | absent | — | required, `operation_id` set | — | — |
| `recovered` | absent | `RECOVERED` | required, `operation_id` set | — | — |
| `recovery_required` | absent | `MANUAL` or `INTERRUPTED` | required, `operation_id` set | — | — |
| `interrupted` | absent | `INTERRUPTED` | required | — | — |
| `listed` | absent | — | — | — | required |

The column groups:

- **Operation members**: `operation_id`, `current_version` (the version running when the result
  is written), `target_version` (the version attempted) and `recovery_available`.
- **Plan members**: `target`, `bundle`, `trust`, `archive` and `server`, exactly as the landed
  `install --plan --json` writes them, unchanged.

`history` results are `listed` or `refused` and carry no operation members. `operation_id` is
null for read-only commands: planning, checks and history create no root state.

Rules:

- **O1** `listed` belongs only to `history`.
- **O2** `verified` is only a plan result, and a plan result is `verified` or `refused`.
- **O3** The table's required, optional and forbidden members hold. `error` codes follow §5.
- **O4** `current_version` and `target_version` are installed versions. For `install`, `update`
  and `downgrade` a non-null `target_version` is a release version (P9).

Producers write the plan members as the landed `install --plan` computes them, with three
guards that keep every result valid:

- a `refused` reason is redacted (§1.7), on stderr as well;
- a bundle path or file name the result cannot carry exactly (a control character, or over its
  bound) is refused with `USAGE` before verification. It is never reported altered.
- `server.version` is the identity's version, or its redacted one-line form (escaped and cut to
  64 code points) when it is not an installed version.

Streams:

- **`--json` alone**: stdout carries the one result. Diagnostics may still go to stderr as
  today.
- **`--events=jsonl`**: stderr carries only event lines, with no mixed text. Every diagnostic
  becomes a redacted `diagnostic` event, including refusals, usage errors and unexpected errors.
  Raw native output goes to the private log, and errors also go into the final result. With
  `--json` as well, stdout still carries the one result.
- **Neither**: human-readable output; this contract does not constrain it.

## 8. The history index

`/var/lib/circuitbreaker-lifecycle/history.json` is root-owned, 0644 and atomically replaced. It
is the redacted summary that `history` reads without elevation. The state utility rewrites it
after every acknowledged checkpoint and on `list`. Its shape is `$defs/history_index`:
`schema_version` (1, versioned on its own), `generated_at` and `operations` (at most 100
entries). When more operations exist, the index carries inspection entries and unfinished
operations first, then the newest finished ones. Older finished operations stay in their
journals and are left out of the index only.

Each entry is one of two forms:

- **A summary**: `inspection_required: false`, `operation_id`, `kind`, `action`, `adapter`,
  `state`, `outcome` (or null while unfinished; `manual` for J6's hand-closed operations),
  `checkpoint` (an interrupted record's last durable checkpoint, or null), `started_at`,
  `updated_at`, `source_version` and `target_version` (installed versions), and
  `recovery_available`.
- **An inspection entry**: `inspection_required: true`, `record` (the journal file name, or
  null) and `reason`. A corrupt or unsupported journal appears this way. It is never silently
  dropped, rewritten or reported as a success.

`history --json` prints a `listed` result whose `operations` are these entries. A malformed ID in
the index is shown as needing inspection and is never used.

The index is written under the lock, so it cannot know that a writer was killed after its last
write. Until the next lock holder (any `begin` or `list`) persists `interrupted`, a killed
operation's summary keeps its last durable state: `outcome` null and a state that is neither
`recovery_required` nor `interrupted`. History presents such an unsettled entry as "in progress or
interrupted" and never as settled; `inspect`, which reads the owner record under privilege,
reports it as `interrupted` (`status=abandoned`). The killed operation is therefore always
discoverable in history, and labelled `interrupted` once any lock holder has run.

The coordinator reads the index only after `checkTrustedFile` (owner uid 0) passes. The exit
codes are:

| Index state | Result |
| --- | --- |
| Missing root or index | empty history, exit 0 |
| Untrusted or unreadable | exit 6 |
| Unparsable | exit 9 |
| Unknown `schema_version` | exit 3 |

## 9. Authority, presentation and secrets

- **Plans describe; they never authorize.** A plan or event a user writes, edits or replays
  grants nothing. Under the lock, the native helper revalidates identity, staged bytes and
  options, recomputes the plan digest from its own inputs, and requires the acknowledgments the
  recomputed plan lists. A plan whose digest it cannot reproduce is refused before mutation.
- **Presentation never reaches authority.** `presentation` is outside the digest. Events and
  rendered text are never read back as state.
- **Secrets are referenced, never carried.** No schema member holds a secret value. The build
  test refuses property names that look like secrets. Secrets live in the recovery point's
  protected storage, and plans and journals reference that point by
  `{operation_id, manifest_digest}`. Logs, events, results and the history index carry no secret.

## 10. The native state utility

`deploy/scripts/lifecycle-state.py` is the only writer of lifecycle state. It is Python 3.9+
standard library only, embeds the four schemas verbatim (a build test keeps the copy equal), and
passes the shared fixtures in `packages/cli/test/fixtures/lifecycle/`. `deploy/lib/lifecycle.sh`
runs it and is its only caller in sub-plan 03.

**Interpreter and install.** `cb_lifecycle_python` resolves the interpreter once per transaction,
before the first mutation: `/usr/bin/python3` when root owns it and the directories above it,
neither group nor others can write them, and it is 3.9 or newer. Otherwise, for a fresh install
only, the caller may pass the verified staged bundle's `python/bin/python3`. Without either it
refuses with 7 before anything changes. `deploy/setup.sh` installs the library, the utility and
`bundle-signature.sh` (which embeds the release bundle keys) into the control plane
`/usr/local/lib/circuitbreaker` (directory 0755, files 0644, the utility 0755, all root's). A
control plane that cannot be installed fails the install. The control plane and the state root lie
outside the release tree and outside every removal scope, so replacing or removing the server
never removes its recovery tools or its audit history.

`lifecycle.sh` runs the utility only from a trusted file (a trusted owner, not writable by group
or others, below directories that pass the state tree's ancestor rule). The library and the
utility speak one protocol, so the copy shipped beside the file the library was read from comes
first: next to it, in its bundle's `deploy/scripts`, or in `deploy/scripts` below the script it is
inlined in. The control plane comes last. A library that bash read from no regular file (piped,
`curl | bash`) looks only in the control plane, and never takes the working directory for its own.
A copy that is not trusted is passed over and never run; with no trusted copy the library refuses
with 7 and names every copy it passed over.

**Layout.** Under the state root: `history.json` (0644), and in `private/` (0700) the lock, the
owner record and `operations/<operation id>/` (0700), which holds `journal.json` (0600) and
`sequence` (0600), the operation's event sequence counter. Every directory and file is checked
for a trusted owner, its exact mode and no symlink before it is used, through directory
descriptors.

**Requests.** One JSON object on stdin, at most 65536 bytes, closed, with the encoding rules of
§1. Free text in a request is at most 4096 code points and is redacted (§1.7) before it is
written. Members:

| `request` | Members | Lock |
| --- | --- | --- |
| `inspect` | `operation_id` | none: reads only |
| `list` | — | held |
| `begin` | `kind`, `action`, `adapter`; optional `plan_digest`, `identity_digest`, `source_version`, `source_artifact_digest`, `target_version`, `target_artifact_digest`, `recovery_operation_id` with `recovery_manifest_digest`, `evidence_check` with `evidence_result` and optional `evidence_detail` | held, bound to no operation |
| `checkpoint` | `operation_id`, `expected_generation`, `state`; optional `step`, `cause`, `outcome`, `error_code` with `error_reason`, the recovery reference and evidence members of `begin` | held, bound to `operation_id` |

A write needs the lock: `CB_LIFECYCLE_LOCK_FD` must name a descriptor of `private/lock` (same
device and inode) that holds the flock, which a fresh description of the lock cannot take, and
`CB_LIFECYCLE_OPERATION` must be the operation the owner record binds. A legacy `begin` records
a version that is not an installed version as null (J11); a transaction's is refused. The utility
fills `sequence`, `at`, `generation`, `updated_at` and an interrupted record's `checkpoint` itself.
A later step of the same progress state replaces the stepped record in place (J3).

**Acknowledgement.** On success the utility prints `key=value` lines on stdout:
`operation_id`, `generation`, `sequence`, `state`, any `warning` (redacted, one line), and
`event`, the checkpoint event (§6) of the record just written. `inspect` prints the summary members,
`status` (`finished`, `unfinished`, `running` or `abandoned`), `reported` (an abandoned operation
is reported as `interrupted`) and `journal`, the canonical journal on one line. `list` prints
counts, `unfinished`, `inspection`, `protected` and `releasable` lines and `retention`. The shell
matches each line against its own shape and never evaluates one; the event goes only to
`CB_LIFECYCLE_EVENT_FD`, after the acknowledgement.

**Durability.** Every record is written to a temporary file in its own directory, flushed,
fsynced, renamed over the old one, and the directory is fsynced before anything is acknowledged.
A failure at any step leaves the old or the new valid record, never a mix, and acknowledges
nothing. `begin` builds the operation's directory under a staging name and renames it into place.
A write that cannot be made durable (a full disk among them) exits 7, so the caller stops before
its next change. A writer whose `expected_generation` is not the journal's is stale and exits 9.
Once a record is durable, the request succeeds: a history index that cannot be rewritten (or
rebuilt) is a warning, since the journal is authoritative.

`cb_lifecycle_checkpoint` learns the journal's current generation (`inspect`) before each
checkpoint and names it as the expected one. Under the held lock only the operation's own
writers can move its journal (the shell, a subshell of it, or a child it handed the lock to, whose
view dies with it), so a parent checkpoints after a child's checkpoint, and a writer that slips in
between still makes it stale. What a shell cannot learn is whether its own checkpoint that went
unacknowledged landed anyway: while the journal still has the generation that shell last saw,
nothing landed and it goes on; once the journal has moved past it, every later checkpoint of the
operation from that shell is stale (9).
INT, TERM and HUP are ignored while a request runs: the caller's trap acts once it returns.

**Reconciliation.** Under the lock, `begin` and `list` close every operation still in progress
other than the one the lock is bound to: its process is gone, so they append `interrupted` with
cause `abandoned` and the last durable checkpoint, closed with outcome `interrupted` when that
checkpoint is before mutation (§4). Then an unfinished `transaction` blocks every `begin` (9). A
record that requires inspection blocks a transaction's `begin` and is a warning for a legacy one.
An unfinished legacy record is a warning only. A new operation ID is always above every ID
already used that day.

**Inspection.** A record whose directory or journal has the wrong owner, mode or type, a
symlink, invalid content, an unknown `schema_version`, or another operation's ID requires
inspection, and so does any other entry of `operations/`. It is listed in the index as an
inspection entry, reported by `inspect` with 9 (3 for an unknown version), and never deleted,
rewritten or counted as a success. A name that is not UTF-8, or holds a character that is not
printable, is shown with those bytes and characters as backslash escapes (`op-bad\xff`), and its
entry's `record` is null.

**Retention.** The utility deletes no record and no recovery point in v1. `list` reports what a
pruner (sub-plan 05 on) may release: every recovery reference an unfinished operation holds and
the newest one an operation that committed recorded (the last successful point) are
`protected`. Other references are `releasable`, and none are while any record requires
inspection (`retention=blocked`), since such a record may hold any reference. The index keeps
unfinished operations and inspection entries ahead of finished ones (§8).

**Exit codes.** 0, 2 (a malformed request, a write without the lock or its operation, an
illegal record or transition, an unknown operation, the seam as root), 3 (an unknown journal
version), 6 (an unsafe tree), 7 (a record that cannot be made durable), 9 (stale writer, a record
that requires inspection, an unfinished transaction blocking `begin`).
