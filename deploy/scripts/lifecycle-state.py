#!/usr/bin/python3 -I
"""The native lifecycle state utility: atomic operation journals and the history index.

It is the only writer of lifecycle state under /var/lib/circuitbreaker-lifecycle
(specs/install/lifecycle-contract.md, section 10). It reads one bounded JSON
request on stdin, answers with `key=value` lines on stdout and exits with a
lifecycle exit code. The requests are `inspect` and `list` (reads; `list` also
rewrites the index) and `begin` and `checkpoint` (writes). A write requires the
host lock that deploy/lib/lifecycle.sh holds: the descriptor named by
CB_LIFECYCLE_LOCK_FD must hold the flock on private/lock, and the operation the
lock is bound to must be the one the request names. A writer must also name the
generation it last saw, so a stale writer is refused rather than overwriting.

Every record is validated against the versioned lifecycle contract before it
is written. The contract's schemas are embedded verbatim below, so nothing is
read from the release tree at run time; tests/build/test_lifecycle_journal.py
keeps the copy equal to packages/cli/schemas and runs this validator over the
same fixtures as packages/cli/src/lifecycle-contract.js.

Every write goes to a temporary file in the same directory, is flushed and
fsynced, atomically renamed over the old record, and the directory is fsynced
before anything is acknowledged. Nothing a journal holds is ever evaluated:
the shell reads only the acknowledgement lines, each matched against its own
shape.

Python 3.9+ standard library only. Run it with `python3 -I`.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any, BinaryIO, NoReturn

EXIT = {
    "OK": 0,
    "USAGE": 2,
    "UNSUPPORTED": 3,
    "NETWORK": 4,
    "TRUST": 5,
    "PERMISSION": 6,
    "PREFLIGHT": 7,
    "RECOVERED": 8,
    "MANUAL": 9,
    "LOCKED": 10,
    "INTERRUPTED": 130,
}

DEFAULT_ROOT = "/var/lib/circuitbreaker-lifecycle"
SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 65536
MAX_REQUEST_TEXT = 4096
MAX_SAFE = 2**53 - 1
MAX_DEPTH = 32

Json = Any
Doc = dict[str, Any]

# packages/cli/schemas/*.schema.json, verbatim (compacted, one schema per line).
# tests/build/test_lifecycle_journal.py fails when this copy drifts from them.
_SCHEMA_TEXT = r'''
{"lifecycle-event":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://circuitbreaker.local/schemas/lifecycle-event.schema.json","title":"CircuitBreakerLifecycleEvent","description":"One lifecycle event, version 1: one line of --events=jsonl or of the native event descriptor. Presentation only; an event never changes or authorizes state. x-fields lists the members each event type carries.","x-max-bytes":4096,"x-fields":{"phase":{"required":["phase","status"],"optional":["duration_ms"]},"progress":{"required":["phase","done","total","unit"],"optional":[]},"checkpoint":{"required":["state","generation"],"optional":[]},"diagnostic":{"required":["level","message"],"optional":["code"]}},"type":"object","additionalProperties":false,"required":["schema_version","operation_id","sequence","at","source","type"],"properties":{"schema_version":{"const":1},"operation_id":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/operation_id"}]},"sequence":{"type":"integer","minimum":1},"at":{"$ref":"#/$defs/timestamp"},"source":{"enum":["coordinator","native"]},"type":{"enum":["phase","progress","checkpoint","diagnostic"]},"phase":{"enum":["preflight","resolve","download","verify","stage","backup","stop","apply","migrate","start","health","commit","recover","remove","cleanup"]},"status":{"enum":["started","completed","failed","skipped"]},"duration_ms":{"type":"integer","minimum":0},"done":{"type":"integer","minimum":0},"total":{"type":["integer","null"],"minimum":0},"unit":{"enum":["bytes","steps"]},"state":{"$ref":"#/$defs/state"},"generation":{"type":"integer","minimum":1},"level":{"enum":["info","warning","error"]},"message":{"$ref":"#/$defs/message_text"},"code":{"$ref":"#/$defs/exit_name"}},"$defs":{"exit_name":{"enum":["USAGE","UNSUPPORTED","NETWORK","TRUST","PERMISSION","PREFLIGHT","RECOVERED","MANUAL","LOCKED","INTERRUPTED"]},"operation_id":{"type":"string","pattern":"^op-[0-9]{8}-[0-9]{3,9}$","format":"cb-operation-id"},"state":{"enum":["planned","staged","verified","recovery_saved","applying","checking","committed","recovering","recovered","recovery_required","interrupted"]},"message_text":{"type":"string","maxLength":900,"pattern":"^[^\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character other than tab or newline","not":{"description":"looks like a credential (a URL password, private key, bearer token or secret assignment); redact it","anyOf":[{"pattern":"[A-Za-z][A-Za-z0-9+.-]*://[^/?#@ \\x00-\\x1f]*:[^/?#@ \\x00-\\x1f]*@"},{"pattern":"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"},{"pattern":"(?:Bearer|bearer|BEARER) [A-Za-z0-9._~+/=-]{8,}"},{"pattern":"(?:[Pp]ass(?:word|wd)|PASS(?:WORD|WD)|[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Aa]pi_?[Kk]ey|API_?KEY|[Vv]ault_[Kk]ey|VAULT_KEY)[ ]?[=:][ ]?[^ \\x00-\\x1f]"}]}},"timestamp":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?Z$","format":"cb-utc-timestamp"}}},
 "lifecycle-plan":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://circuitbreaker.local/schemas/lifecycle-plan.schema.json","title":"CircuitBreakerLifecyclePlan","description":"A lifecycle execution plan, version 1. Describes; never authorizes: the native helper recomputes its digest from its own inputs. Field rules beyond this schema: specs/install/lifecycle-contract.md.","x-max-bytes":65536,"type":"object","additionalProperties":false,"required":["schema_version","action","adapter","source","target","compatibility","options","downtime","recovery","data","trust","acknowledgments"],"properties":{"schema_version":{"const":1},"plan_digest":{"$ref":"#/$defs/digest"},"presentation":{"type":"object","additionalProperties":false,"properties":{"summary":{"$ref":"#/$defs/brief_text"},"lines":{"type":"array","maxItems":32,"items":{"$ref":"#/$defs/brief_text"}}}},"action":{"enum":["install","update","downgrade","rollback","recover","uninstall"]},"adapter":{"$ref":"#/$defs/adapter"},"source":{"type":["object","null"],"additionalProperties":false,"required":["version","identity_digest","artifact_digest","schema_revision"],"properties":{"version":{"$ref":"#/$defs/installed_version"},"identity_digest":{"$ref":"#/$defs/digest"},"artifact_digest":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/digest"}]},"schema_revision":{"$ref":"#/$defs/revision"}}},"target":{"type":["object","null"],"additionalProperties":false,"required":["version","arch","channel","artifact","schema_revision"],"properties":{"version":{"$ref":"#/$defs/installed_version"},"arch":{"enum":["amd64","arm64"]},"channel":{"enum":["stable","candidate",null]},"artifact":{"type":"object","additionalProperties":false,"required":["name","digest"],"properties":{"name":{"type":"string","pattern":"^[A-Za-z0-9][A-Za-z0-9._+:/@-]{0,254}$"},"digest":{"$ref":"#/$defs/digest"}}},"schema_revision":{"$ref":"#/$defs/revision"}}},"compatibility":{"type":"object","additionalProperties":false,"required":["management","schema","transition_digest"],"properties":{"management":{"enum":["certified","uncertified","not_applicable"]},"schema":{"enum":["none","forward","compatible","incompatible"]},"transition_digest":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/digest"}]}}},"options":{"type":["object","null"],"additionalProperties":false,"required":["port","fqdn","cert_type","email","data_dir","tls","docker","airgap"],"properties":{"port":{"type":["integer","null"],"minimum":1,"maximum":65535},"fqdn":{"type":["string","null"],"maxLength":253,"pattern":"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"},"cert_type":{"enum":["self-signed","letsencrypt",null]},"email":{"type":["string","null"],"maxLength":254,"pattern":"^[^@ \\x00-\\x1f\\x7f]{1,64}@[A-Za-z0-9.-]{1,253}$"},"data_dir":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/path"}]},"tls":{"type":"boolean"},"docker":{"type":"boolean"},"airgap":{"type":"boolean"}}},"downtime":{"enum":["none","restart","outage"]},"recovery":{"type":"object","additionalProperties":false,"required":["mode","ref"],"properties":{"mode":{"enum":["none","new_point","existing_point"]},"ref":{"$ref":"#/$defs/recovery_ref"}}},"data":{"type":"object","additionalProperties":false,"required":["effect","restore_point_at","scope_digest"],"properties":{"effect":{"enum":["none","retained","migrated","restored","removed"]},"restore_point_at":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/timestamp"}]},"scope_digest":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/digest"}]}}},"trust":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/trust"}]},"acknowledgments":{"type":"array","minItems":1,"maxItems":3,"uniqueItems":true,"items":{"enum":["confirm","restore_data","purge"]}}},"$defs":{"adapter":{"enum":["native","mono","package","proxmox"]},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"installed_version":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[^\\x00-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character"},"operation_id":{"type":"string","pattern":"^op-[0-9]{8}-[0-9]{3,9}$","format":"cb-operation-id"},"path":{"type":"string","maxLength":4096,"pattern":"^/(?:(?!\\.\\.?(?:/|$))[^/\\x00-\\x1f\\x7f-\\x9f]+(?:/(?!\\.\\.?(?:/|$))[^/\\x00-\\x1f\\x7f-\\x9f]+)*)?$"},"recovery_ref":{"type":["object","null"],"additionalProperties":false,"required":["operation_id","manifest_digest"],"properties":{"operation_id":{"$ref":"#/$defs/operation_id"},"manifest_digest":{"$ref":"#/$defs/digest"}}},"revision":{"type":["string","null"],"pattern":"^[0-9A-Za-z_]{1,64}$"},"brief_text":{"type":"string","maxLength":256,"pattern":"^[^\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character other than tab or newline","not":{"description":"looks like a credential (a URL password, private key, bearer token or secret assignment); redact it","anyOf":[{"pattern":"[A-Za-z][A-Za-z0-9+.-]*://[^/?#@ \\x00-\\x1f]*:[^/?#@ \\x00-\\x1f]*@"},{"pattern":"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"},{"pattern":"(?:Bearer|bearer|BEARER) [A-Za-z0-9._~+/=-]{8,}"},{"pattern":"(?:[Pp]ass(?:word|wd)|PASS(?:WORD|WD)|[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Aa]pi_?[Kk]ey|API_?KEY|[Vv]ault_[Kk]ey|VAULT_KEY)[ ]?[=:][ ]?[^ \\x00-\\x1f]"}]}},"timestamp":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?Z$","format":"cb-utc-timestamp"},"trust":{"type":"object","additionalProperties":false,"required":["signature","provenance"],"properties":{"signature":{"oneOf":[{"type":"object","additionalProperties":false,"required":["key_id"],"properties":{"key_id":{"type":"string","pattern":"^[0-9a-f]{16}$"}}},{"type":"object","additionalProperties":false,"required":["unsigned"],"properties":{"unsigned":{"enum":["pinned","explicit-older"]}}}]},"provenance":{"enum":["verified","skipped-airgap","not-applicable"]}}},"version":{"type":"string","maxLength":64,"pattern":"^[0-9]+\\.[0-9]+\\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"}}},
 "lifecycle-result":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://circuitbreaker.local/schemas/lifecycle-result.schema.json","title":"CircuitBreakerLifecycleResult","description":"The one final --json result of a lifecycle command, version 1, including install --plan's existing output unchanged. Which members each outcome carries: specs/install/lifecycle-contract.md. $defs/history_index is the derived history.json index, versioned on its own.","x-max-bytes":262144,"type":"object","additionalProperties":false,"required":["schema_version","action","outcome"],"properties":{"schema_version":{"const":1},"action":{"enum":["install","update","downgrade","rollback","recover","uninstall","history"]},"plan":{"const":true},"outcome":{"enum":["verified","refused","available","no_change","committed","recovered","recovery_required","interrupted","listed"]},"operation_id":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/operation_id"}]},"current_version":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/installed_version"}]},"target_version":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/installed_version"}]},"recovery_available":{"type":"boolean"},"error":{"$ref":"#/$defs/error"},"target":{"type":"object","additionalProperties":false,"required":["version","channel","arch","explicit_version"],"properties":{"version":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/version"}]},"channel":{"enum":["stable","candidate",null]},"arch":{"enum":["amd64","arm64",null]},"explicit_version":{"type":"boolean"}}},"bundle":{"type":"object","additionalProperties":false,"required":["name","sha256","path"],"properties":{"name":{"$ref":"#/$defs/file_name"},"sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"path":{"$ref":"#/$defs/path"}}},"trust":{"$ref":"#/$defs/trust"},"archive":{"type":"object","additionalProperties":false,"required":["entries","total_bytes"],"properties":{"entries":{"type":"integer","minimum":0},"total_bytes":{"type":"integer","minimum":0}}},"server":{"type":["object","null"],"additionalProperties":false,"required":["version","mode"],"properties":{"version":{"$ref":"#/$defs/installed_version"},"mode":{"$ref":"#/$defs/adapter"}}},"operations":{"type":"array","maxItems":100,"items":{"$ref":"#/$defs/history_entry"}}},"$defs":{"adapter":{"enum":["native","mono","package","proxmox"]},"brief_text":{"type":"string","maxLength":256,"pattern":"^[^\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character other than tab or newline","not":{"description":"looks like a credential (a URL password, private key, bearer token or secret assignment); redact it","anyOf":[{"pattern":"[A-Za-z][A-Za-z0-9+.-]*://[^/?#@ \\x00-\\x1f]*:[^/?#@ \\x00-\\x1f]*@"},{"pattern":"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"},{"pattern":"(?:Bearer|bearer|BEARER) [A-Za-z0-9._~+/=-]{8,}"},{"pattern":"(?:[Pp]ass(?:word|wd)|PASS(?:WORD|WD)|[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Aa]pi_?[Kk]ey|API_?KEY|[Vv]ault_[Kk]ey|VAULT_KEY)[ ]?[=:][ ]?[^ \\x00-\\x1f]"}]}},"error":{"type":"object","additionalProperties":false,"required":["code","reason"],"properties":{"code":{"$ref":"#/$defs/exit_name"},"reason":{"$ref":"#/$defs/text"}}},"exit_name":{"enum":["USAGE","UNSUPPORTED","NETWORK","TRUST","PERMISSION","PREFLIGHT","RECOVERED","MANUAL","LOCKED","INTERRUPTED"]},"file_name":{"type":"string","minLength":1,"maxLength":255,"pattern":"^[^/\\x00-\\x1f\\x7f-\\x9f]*$"},"history_entry":{"oneOf":[{"type":"object","additionalProperties":false,"required":["inspection_required","operation_id","kind","action","adapter","state","outcome","checkpoint","started_at","updated_at","source_version","target_version","recovery_available"],"properties":{"inspection_required":{"const":false},"operation_id":{"$ref":"#/$defs/operation_id"},"kind":{"$ref":"#/$defs/kind"},"action":{"$ref":"#/$defs/journal_action"},"adapter":{"$ref":"#/$defs/adapter"},"state":{"$ref":"#/$defs/state"},"outcome":{"enum":["committed","recovered","refused","interrupted","manual",null]},"checkpoint":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/state"}]},"started_at":{"$ref":"#/$defs/timestamp"},"updated_at":{"$ref":"#/$defs/timestamp"},"source_version":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/installed_version"}]},"target_version":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/installed_version"}]},"recovery_available":{"type":"boolean"}}},{"type":"object","additionalProperties":false,"required":["inspection_required","record","reason"],"properties":{"inspection_required":{"const":true},"record":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/file_name"}]},"reason":{"$ref":"#/$defs/brief_text"}}}]},"installed_version":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[^\\x00-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character"},"history_index":{"x-max-bytes":262144,"type":"object","additionalProperties":false,"required":["schema_version","generated_at","operations"],"properties":{"schema_version":{"const":1},"generated_at":{"$ref":"#/$defs/timestamp"},"operations":{"type":"array","maxItems":100,"items":{"$ref":"#/$defs/history_entry"}}}},"journal_action":{"enum":["install","update","downgrade","rollback","recover","uninstall","restore","migrate","backup","vault_recover","restart"]},"kind":{"enum":["transaction","legacy"]},"operation_id":{"type":"string","pattern":"^op-[0-9]{8}-[0-9]{3,9}$","format":"cb-operation-id"},"path":{"type":"string","maxLength":4096,"pattern":"^/(?:(?!\\.\\.?(?:/|$))[^/\\x00-\\x1f\\x7f-\\x9f]+(?:/(?!\\.\\.?(?:/|$))[^/\\x00-\\x1f\\x7f-\\x9f]+)*)?$"},"state":{"enum":["planned","staged","verified","recovery_saved","applying","checking","committed","recovering","recovered","recovery_required","interrupted"]},"text":{"type":"string","maxLength":4096,"pattern":"^[^\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character other than tab or newline","not":{"description":"looks like a credential (a URL password, private key, bearer token or secret assignment); redact it","anyOf":[{"pattern":"[A-Za-z][A-Za-z0-9+.-]*://[^/?#@ \\x00-\\x1f]*:[^/?#@ \\x00-\\x1f]*@"},{"pattern":"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"},{"pattern":"(?:Bearer|bearer|BEARER) [A-Za-z0-9._~+/=-]{8,}"},{"pattern":"(?:[Pp]ass(?:word|wd)|PASS(?:WORD|WD)|[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Aa]pi_?[Kk]ey|API_?KEY|[Vv]ault_[Kk]ey|VAULT_KEY)[ ]?[=:][ ]?[^ \\x00-\\x1f]"}]}},"timestamp":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?Z$","format":"cb-utc-timestamp"},"trust":{"type":"object","additionalProperties":false,"required":["signature","provenance"],"properties":{"signature":{"oneOf":[{"type":"object","additionalProperties":false,"required":["key_id"],"properties":{"key_id":{"type":"string","pattern":"^[0-9a-f]{16}$"}}},{"type":"object","additionalProperties":false,"required":["unsigned"],"properties":{"unsigned":{"enum":["pinned","explicit-older"]}}}]},"provenance":{"enum":["verified","skipped-airgap","not-applicable"]}}},"version":{"type":"string","maxLength":64,"pattern":"^[0-9]+\\.[0-9]+\\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"}}},
 "operation-journal":{"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"https://circuitbreaker.local/schemas/operation-journal.schema.json","title":"CircuitBreakerOperationJournal","description":"One operation's root-owned journal, version 1, atomically replaced at each durable checkpoint. Authoritative lifecycle state; never contains secret values. x-lifecycle is the state machine; the rules that walk it: specs/install/lifecycle-contract.md.","x-max-bytes":65536,"x-lifecycle":{"initial":{"transaction":"planned","legacy":"applying"},"pre_mutation":["planned","staged","verified","recovery_saved"],"progress_states":["applying","checking","recovering"],"max_recovery_attempts":3,"causes":{"interrupted":["interrupted","abandoned"],"recovery_required":["interrupted","apply_failed","check_failed","recovery_failed"]},"transitions":{"transaction":{"planned":["staged","interrupted"],"staged":["verified","interrupted"],"verified":["recovery_saved","applying","interrupted"],"recovery_saved":["applying","interrupted"],"applying":["checking","recovering","recovery_required","interrupted"],"checking":["committed","recovering","recovery_required","interrupted"],"committed":[],"recovering":["recovered","recovery_required","interrupted"],"recovered":[],"recovery_required":["recovering"],"interrupted":["recovering","recovery_required"]},"legacy":{"applying":["committed","recovery_required","interrupted"]}}},"type":"object","additionalProperties":false,"required":["schema_version","operation_id","kind","action","adapter","generation","plan_digest","identity_digest","source","target","recovery","evidence","started_at","updated_at","checkpoints"],"properties":{"schema_version":{"const":1},"operation_id":{"$ref":"#/$defs/operation_id"},"kind":{"$ref":"#/$defs/kind"},"action":{"$ref":"#/$defs/journal_action"},"adapter":{"$ref":"#/$defs/adapter"},"generation":{"type":"integer","minimum":1},"plan_digest":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/digest"}]},"identity_digest":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/digest"}]},"source":{"$ref":"#/$defs/release"},"target":{"$ref":"#/$defs/release"},"recovery":{"$ref":"#/$defs/recovery_ref"},"evidence":{"type":"array","maxItems":16,"items":{"type":"object","additionalProperties":false,"required":["check","result","detail"],"properties":{"check":{"enum":["signature","provenance","digest","archive","compatibility","recovery_point","health","version","schema","identity"]},"result":{"enum":["passed","failed","skipped"]},"detail":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/brief_text"}]}}}},"started_at":{"$ref":"#/$defs/timestamp"},"updated_at":{"$ref":"#/$defs/timestamp"},"checkpoints":{"type":"array","minItems":1,"maxItems":32,"items":{"type":"object","additionalProperties":false,"required":["sequence","state","at"],"properties":{"sequence":{"type":"integer","minimum":1},"state":{"$ref":"#/$defs/state"},"at":{"$ref":"#/$defs/timestamp"},"step":{"type":"string","pattern":"^[a-z][a-z0-9_]{0,63}$"},"cause":{"enum":["interrupted","abandoned","apply_failed","check_failed","recovery_failed"]},"checkpoint":{"$ref":"#/$defs/state"},"outcome":{"enum":["committed","recovered","refused","interrupted","manual"]},"error":{"$ref":"#/$defs/journal_error"}}}}},"$defs":{"adapter":{"enum":["native","mono","package","proxmox"]},"digest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},"journal_error":{"type":"object","additionalProperties":false,"required":["code","reason"],"properties":{"code":{"$ref":"#/$defs/exit_name"},"reason":{"$ref":"#/$defs/brief_text"}}},"installed_version":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[^\\x00-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character"},"exit_name":{"enum":["USAGE","UNSUPPORTED","NETWORK","TRUST","PERMISSION","PREFLIGHT","RECOVERED","MANUAL","LOCKED","INTERRUPTED"]},"journal_action":{"enum":["install","update","downgrade","rollback","recover","uninstall","restore","migrate","backup","vault_recover","restart"]},"kind":{"enum":["transaction","legacy"]},"operation_id":{"type":"string","pattern":"^op-[0-9]{8}-[0-9]{3,9}$","format":"cb-operation-id"},"recovery_ref":{"type":["object","null"],"additionalProperties":false,"required":["operation_id","manifest_digest"],"properties":{"operation_id":{"$ref":"#/$defs/operation_id"},"manifest_digest":{"$ref":"#/$defs/digest"}}},"release":{"type":["object","null"],"additionalProperties":false,"required":["version","artifact_digest"],"properties":{"version":{"$ref":"#/$defs/installed_version"},"artifact_digest":{"anyOf":[{"type":"null"},{"$ref":"#/$defs/digest"}]}}},"state":{"enum":["planned","staged","verified","recovery_saved","applying","checking","committed","recovering","recovered","recovery_required","interrupted"]},"brief_text":{"type":"string","maxLength":256,"pattern":"^[^\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f]*$","x-reason":"contains a control character other than tab or newline","not":{"description":"looks like a credential (a URL password, private key, bearer token or secret assignment); redact it","anyOf":[{"pattern":"[A-Za-z][A-Za-z0-9+.-]*://[^/?#@ \\x00-\\x1f]*:[^/?#@ \\x00-\\x1f]*@"},{"pattern":"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"},{"pattern":"(?:Bearer|bearer|BEARER) [A-Za-z0-9._~+/=-]{8,}"},{"pattern":"(?:[Pp]ass(?:word|wd)|PASS(?:WORD|WD)|[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Aa]pi_?[Kk]ey|API_?KEY|[Vv]ault_[Kk]ey|VAULT_KEY)[ ]?[=:][ ]?[^ \\x00-\\x1f]"}]}},"timestamp":{"type":"string","pattern":"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?Z$","format":"cb-utc-timestamp"},"version":{"type":"string","maxLength":64,"pattern":"^[0-9]+\\.[0-9]+\\.[0-9]+(?:-[0-9A-Za-z.-]+)?$"}}}}
'''
_SCHEMAS: Doc = json.loads(_SCHEMA_TEXT)
PLAN: Doc = _SCHEMAS["lifecycle-plan"]
EVENT: Doc = _SCHEMAS["lifecycle-event"]
RESULT: Doc = _SCHEMAS["lifecycle-result"]
JOURNAL: Doc = _SCHEMAS["operation-journal"]
LIFECYCLE: Doc = JOURNAL["x-lifecycle"]
STATES: list[str] = list(JOURNAL["$defs"]["state"]["enum"])


class ContractError(Exception):
    """A document refused by the lifecycle contract; `unsupported` marks an unknown version."""

    def __init__(self, path: str, reason: str, unsupported: bool = False) -> None:
        super().__init__(f"{path}: {reason}" if path else reason)
        self.path = path
        self.reason = reason
        self.unsupported = unsupported


class StateError(Exception):
    """A refused request: the lifecycle exit code and the message for stderr."""

    def __init__(self, code: str, message: str, lines: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.lines = lines or []


def _fail(path: str, reason: str) -> NoReturn:
    raise ContractError(path, reason)


def _pattern(source: str) -> re.Pattern[str]:
    """Compile a contract pattern; Python's `$` also matches before a final newline, so it reads `\\Z`."""
    return re.compile(source.replace("$", r"\Z"))


_REGEXES: dict[str, re.Pattern[str]] = {}


def _regex(source: str) -> re.Pattern[str]:
    if source not in _REGEXES:
        _REGEXES[source] = _pattern(source)
    return _REGEXES[source]


RESOLVED = {"install", "update", "downgrade"}
_RELEASE = _pattern(JOURNAL["$defs"]["version"]["pattern"])


def _is_release(version: Json) -> bool:
    return (
        isinstance(version, str)
        and _RELEASE.search(version) is not None
        and len(version) <= JOURNAL["$defs"]["version"]["maxLength"]
    )


# --- Canonical form (contract section 2): what both validators hash and size.

_KEY = re.compile(r"[a-z][a-z0-9_]*\Z")
_SURROGATE = re.compile("[\ud800-\udfff]")


def _js(value: Json) -> str:
    """JSON.stringify of a scalar, for messages that must read as the coordinator's do."""
    return json.dumps(value, ensure_ascii=False)


def _canonical(value: Json, path: str, depth: int) -> str:
    if depth > MAX_DEPTH:
        _fail(path, f"nested deeper than {MAX_DEPTH} levels")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        if _SURROGATE.search(value):
            _fail(path, "contains a lone surrogate")
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        if abs(value) > MAX_SAFE:
            _fail(path, f"{value} is not a safe integer (no fractions, -0 or values beyond 2^53-1)")
        return str(value)
    if isinstance(value, float):
        _fail(path, f"{value!r} is not a safe integer (no fractions, -0 or values beyond 2^53-1)")
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item, f"{path}/{i}", depth + 1) for i, item in enumerate(value)) + "]"
    if isinstance(value, dict):
        members = []
        for key in sorted(value):
            if not isinstance(key, str) or not _KEY.match(key):
                _fail(f"{path}/{key}", f"key {_js(str(key))[:66]} is not lowercase snake_case ASCII")
            members.append(f"{json.dumps(key)}:{_canonical(value[key], f'{path}/{key}', depth + 1)}")
        return "{" + ",".join(members) + "}"
    _fail(path, f"{type(value).__name__} is not a JSON value")


def canonicalize(value: Json) -> str:
    """The canonical JSON text: sorted snake_case keys, no whitespace, safe integers, JSON.stringify escapes."""
    return _canonical(value, "", 0)


def plan_digest(plan: Doc) -> str:
    """sha256 of the canonical plan without its presentation and its own digest."""
    bound = {k: v for k, v in plan.items() if k not in ("plan_digest", "presentation")}
    return "sha256:" + hashlib.sha256(canonicalize(bound).encode("utf-8")).hexdigest()


# --- The schema subset (contract section 1).


def _real_date(year: int, month: int, day: int) -> bool:
    if year < 1 or not 1 <= month <= 12 or day < 1:
        return False
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return day <= days


def _timestamp_format(s: str) -> bool:
    return (
        _real_date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
        and int(s[11:13]) <= 23
        and int(s[14:16]) <= 59
        and int(s[17:19]) <= 59
    )


FORMATS: dict[str, Callable[[str], bool]] = {
    "cb-utc-timestamp": _timestamp_format,
    "cb-operation-id": lambda s: _real_date(int(s[3:7]), int(s[7:9]), int(s[9:11])),
}
_SECRET_NAME = re.compile(r"pass(word|wd)?|secret|token|credential|api_?key|private_key|vault_key|^key$")


def _type_of(value: Json) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _same(a: Json, b: Json) -> bool:
    """JavaScript's ===: equal by JSON type as well as by value, so true is not 1."""
    return _type_of(a) == _type_of(b) and a == b


Refusal = tuple[str, str, str]  # path, reason, keyword


def _explain(errors: list[Refusal], path: str) -> Refusal:
    """A branch that failed on a discriminating const, or on the instance's own type, was not the one meant."""
    for error in errors:
        if error[2] != "const" and not (error[2] == "type" and error[0] == path):
            return error
    return errors[0]


def _check(node: Doc, defs: Doc, value: Json, path: str) -> Refusal | None:
    if "$ref" in node:
        return _check(defs[node["$ref"][len("#/$defs/"):]], defs, value, path)

    def refuse(reason: str, keyword: str, at: str | None = None) -> Refusal:
        return (path if at is None else at, reason, keyword)

    kind = _type_of(value)
    if "type" in node:
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if kind not in types:
            return refuse(f"must be {' or '.join(types)}", "type")
    if "const" in node and not _same(value, node["const"]):
        return refuse(f"must be {_js(node['const'])}", "const")
    if "enum" in node and not any(_same(value, option) for option in node["enum"]):
        return refuse("must be one of " + ", ".join(_js(option) for option in node["enum"]), "enum")
    if kind == "string":
        length = len(value)
        if length < node.get("minLength", 0):
            return refuse(f"must be at least {node['minLength']} characters", "minLength")
        if "maxLength" in node and length > node["maxLength"]:
            return refuse(f"must be at most {node['maxLength']} characters", "maxLength")
        if "pattern" in node and not _regex(node["pattern"]).search(value):
            return refuse(node.get("x-reason", f"does not match the pattern {node['pattern']}"), "pattern")
        if "format" in node and not FORMATS[node["format"]](value):
            return refuse("is not a real calendar date and time", "format")
    if kind in ("integer", "number"):
        if "minimum" in node and value < node["minimum"]:
            return refuse(f"must be at least {node['minimum']}", "minimum")
        if "maximum" in node and value > node["maximum"]:
            return refuse(f"must be at most {node['maximum']}", "maximum")
    if kind == "array":
        if len(value) < node.get("minItems", 0):
            return refuse(f"must have at least {node['minItems']} item(s)", "minItems")
        if "maxItems" in node and len(value) > node["maxItems"]:
            return refuse(f"must have at most {node['maxItems']} items", "maxItems")
        if node.get("uniqueItems"):
            # JavaScript's Set: scalars compare by value, objects and arrays by identity.
            scalars = [(_type_of(v), v) for v in value if not isinstance(v, (dict, list))]
            if len(set(scalars)) != len(scalars):
                return refuse("items must be unique", "uniqueItems")
        if "items" in node:
            for i, item in enumerate(value):
                error = _check(node["items"], defs, item, f"{path}/{i}")
                if error:
                    return error
    if kind == "object" and node.get("additionalProperties") is False:
        properties = node.get("properties", {})
        for key, sub in properties.items():
            if key in value:
                error = _check(sub, defs, value[key], f"{path}/{key}")
                if error:
                    return error
        for key in node.get("required", []):
            if key not in value:
                return refuse(f"{key} is required", "required", f"{path}/{key}")
        for key in value:
            if key in properties:
                continue
            if _SECRET_NAME.search(key):
                reason = f"{key} looks like a secret field and is not allowed; record a reference to protected storage instead"
            else:
                reason = f"{key} is not allowed here"
            return refuse(reason, "additionalProperties", f"{path}/{key}")
    for keyword in ("oneOf", "anyOf"):
        if keyword not in node:
            continue
        errors = [_check(branch, defs, value, path) for branch in node[keyword]]
        matched = sum(1 for e in errors if e is None)
        if matched == 0:
            return _explain([e for e in errors if e is not None], path)
        if keyword == "oneOf" and matched > 1:
            return refuse("matches more than one alternative", "oneOf")
    if "not" in node and _check(node["not"], defs, value, path) is None:
        return refuse(node["not"].get("description", "has a forbidden shape"), "not")
    return None


# --- Cross-field rules: the contract's P (plan), E (event), O (result) and J (journal) rules.

ERROR_OUTCOMES = {"refused", "recovered", "recovery_required", "interrupted"}


def _error_code_problem(outcome: str, code: str) -> str | None:
    if outcome == "recovered":
        return None if code == "RECOVERED" else "a recovered result uses code RECOVERED"
    if outcome == "recovery_required":
        if code in ("MANUAL", "INTERRUPTED"):
            return None
        return "recovery_required uses code MANUAL, or INTERRUPTED when a signal caused it"
    if outcome == "interrupted":
        return None if code == "INTERRUPTED" else "an interruption uses code INTERRUPTED"
    if code in ("RECOVERED", "INTERRUPTED"):
        return "a refusal uses the code of the check that refused, not RECOVERED or INTERRUPTED"
    return None


def _plan_rules(p: Doc) -> None:
    if "plan_digest" in p and p["plan_digest"] != plan_digest(p):
        _fail("/plan_digest", "does not match the plan; recompute it from the canonical plan")
    action = p["action"]
    if action == "install" and p["source"] is not None:
        _fail("/source", "an install has no source; the host runs no server yet")
    if action != "install" and p["source"] is None:
        _fail("/source", f"{action} needs a source: the installed server it acts on")
    targetless = action in ("uninstall", "recover")
    if targetless and p["target"] is not None:
        _fail("/target", f"{action} has no target release")
    if not targetless and p["target"] is None:
        _fail("/target", f"{action} needs a target release")
    if action in RESOLVED and p["trust"] is None:
        _fail("/trust", f"{action} needs trust evidence for its target")
    if action in RESOLVED and not _is_release(p["target"]["version"]):
        _fail("/target/version", f"{action} targets a resolved release, named like 0.4.7")
    if p["target"] is None and p["trust"] is not None:
        _fail("/trust", "trust describes a target, and this plan has none")
    recovery = p["recovery"]
    if recovery["mode"] == "existing_point" and recovery["ref"] is None:
        _fail("/recovery/ref", "existing_point names the recovery point it restores")
    if recovery["mode"] != "existing_point" and recovery["ref"] is not None:
        _fail("/recovery/ref", "only existing_point names a recovery point")
    if action == "install" and recovery["mode"] != "none":
        _fail("/recovery/mode", "an install has nothing to recover; its mode is none")
    if action == "rollback" and recovery["mode"] != "existing_point":
        _fail("/recovery/mode", "a rollback restores an existing_point")
    if (p["compatibility"]["management"] == "not_applicable") != (p["source"] is None):
        _fail("/compatibility/management", "not_applicable means no server is installed, and only then")
    data = p["data"]
    restored = data["effect"] == "restored"
    if restored != (data["restore_point_at"] is not None):
        _fail("/data/restore_point_at", "restore_point_at dates the restored point and is set only when data is restored")
    if (action == "uninstall") != (data["scope_digest"] is not None):
        _fail("/data/scope_digest", "scope_digest binds the removal scope of an uninstall, and only of one")
    acks = p["acknowledgments"]
    if "confirm" not in acks:
        _fail("/acknowledgments", "every plan requires confirm")
    if restored != ("restore_data" in acks):
        _fail("/acknowledgments", "restore_data is required exactly when data is restored")
    if (data["effect"] == "removed") != ("purge" in acks):
        _fail("/acknowledgments", "purge is required exactly when data is removed")


def _event_rules(e: Doc) -> None:
    fields = EVENT["x-fields"][e["type"]]
    allowed = set(EVENT["required"]) | set(fields["required"]) | set(fields["optional"])
    for key in e:
        if key not in allowed:
            _fail(f"/{key}", f"{key} is not allowed in a {e['type']} event")
    for key in fields["required"]:
        if key not in e:
            _fail(f"/{key}", f"{key} is required in a {e['type']} event")
    if e["type"] == "phase" and "duration_ms" in e and e["status"] not in ("completed", "failed"):
        _fail("/duration_ms", "a duration belongs to a completed or failed phase")
    if e["type"] == "progress" and e["total"] is not None and e["done"] > e["total"]:
        _fail("/done", "done exceeds total")
    if e["type"] == "checkpoint" and e["operation_id"] is None:
        _fail("/operation_id", "a checkpoint event names its operation")
    if e["type"] == "checkpoint" and e["source"] != "native":
        _fail("/source", "checkpoint events come only from the native state utility")
    if e["operation_id"] is None and e["source"] != "coordinator":
        _fail("/operation_id", "native events always name their operation")


PLAN_FIELDS = ("target", "bundle", "trust", "archive", "server")
OPERATION_FIELDS = ("operation_id", "current_version", "target_version", "recovery_available")
_MISSING = object()


def _result_rules(r: Doc) -> None:
    action, outcome = r["action"], r["outcome"]
    history = action == "history"
    if history and outcome not in ("listed", "refused"):
        _fail("/outcome", f"history lists or refuses; it is never {outcome}")
    if not history and outcome == "listed":
        _fail("/outcome", "listed is only the history result")
    if r.get("plan") is True:
        if history:
            _fail("/plan", "history has no plan")
        if outcome not in ("verified", "refused"):
            _fail("/outcome", f"a plan result is verified or refused, never {outcome}")
        if r.get("operation_id") is not None:
            _fail("/operation_id", "a plan creates no operation; its operation_id is null")
    elif outcome == "verified":
        _fail("/plan", "verified results are plan results (plan: true)")
    for field in PLAN_FIELDS:
        if outcome == "verified" and field not in r:
            _fail(f"/{field}", f"a verified plan result carries {field}")
        if outcome != "verified" and field in r:
            _fail(f"/{field}", f"{field} only appears in a verified plan result")
    if outcome == "listed" and "operations" not in r:
        _fail("/operations", "a listed result carries operations")
    if outcome != "listed" and "operations" in r:
        _fail("/operations", "operations only appear in a listed history result")
    for field in OPERATION_FIELDS:
        if history and field in r:
            _fail(f"/{field}", f"{field} does not appear in a history result")
        if not history and r.get("plan") is not True and field not in r:
            _fail(f"/{field}", f"{field} is required in an operation result")
    error = r.get("error")
    if outcome in ERROR_OUTCOMES and not error:
        _fail("/error", f"a {outcome} result carries an error")
    if outcome not in ERROR_OUTCOMES and error:
        _fail("/error", f"a {outcome} result carries no error")
    problem = _error_code_problem(outcome, error["code"]) if error else None
    if problem:
        _fail("/error/code", problem)
    if outcome in ("committed", "recovered", "recovery_required") and r.get("operation_id", _MISSING) is None:
        _fail("/operation_id", f"a {outcome} result names its operation")
    if outcome == "available" and r.get("operation_id", _MISSING) is not None:
        _fail("/operation_id", "a release check creates no operation")
    if outcome == "available" and r.get("target_version", _MISSING) is None:
        _fail("/target_version", "an available result names the newer release")
    target_version = r.get("target_version")
    if action in RESOLVED and isinstance(target_version, str) and not _is_release(target_version):
        _fail("/target_version", f"{action} targets a resolved release, named like 0.4.7")


def _checkpoint_rules(c: Doc, at: str) -> None:
    pre_mutation = LIFECYCLE["pre_mutation"]
    progress_states = LIFECYCLE["progress_states"]
    state = c["state"]
    if "step" in c and state not in progress_states:
        _fail(f"{at}/step", f"a step only marks progress within {', '.join(progress_states)}")
    allowed_causes = LIFECYCLE["causes"].get(state)
    if allowed_causes and "cause" not in c:
        _fail(f"{at}/cause", f"{state} records need a cause")
    if allowed_causes and c.get("cause") not in allowed_causes:
        _fail(f"{at}/cause", f"{state} takes cause {', '.join(allowed_causes)}")
    if not allowed_causes and "cause" in c:
        _fail(f"{at}/cause", "only interrupted and recovery_required records carry a cause")
    if (state == "interrupted") != ("checkpoint" in c):
        if state == "interrupted":
            _fail(f"{at}/checkpoint", "an interrupted record names its last durable checkpoint")
        _fail(f"{at}/checkpoint", "only an interrupted record names a checkpoint")
    outcome = c.get("outcome")
    for closing in ("committed", "recovered"):
        if (state == closing) != (outcome == closing):
            _fail(f"{at}/outcome", f"a {closing} record closes with outcome {closing}, and only it does")
    if outcome == "refused" and state not in pre_mutation:
        _fail(f"{at}/outcome", "refused only closes an operation before mutation")
    if outcome == "interrupted" and not (state == "interrupted" and c.get("checkpoint") in pre_mutation):
        _fail(f"{at}/outcome", "interrupted only closes an operation interrupted before mutation")
    if state == "interrupted" and c.get("checkpoint") in pre_mutation and outcome != "interrupted":
        _fail(
            f"{at}/outcome",
            "an interruption before mutation changed nothing, so it closes the operation with outcome interrupted",
        )
    if state == "interrupted" and c.get("checkpoint") not in pre_mutation and c.get("cause") != "abandoned":
        _fail(
            f"{at}/cause",
            "after mutation a trap records recovery_required with cause interrupted; "
            "an interrupted record after mutation is only abandoned (no trap ran)",
        )
    if outcome == "manual" and state != "recovery_required":
        _fail(f"{at}/outcome", "manual only closes a recovery_required operation")
    error_as = "refused" if outcome == "refused" else state
    needs_error = error_as in ("refused", "recovered", "recovery_required")
    error = c.get("error")
    if needs_error and not error:
        _fail(f"{at}/error", f"a {error_as} record carries an error")
    if error and not needs_error and error_as != "interrupted":
        _fail(f"{at}/error", "only refused, recovered, recovery_required and interrupted records carry an error")
    problem = _error_code_problem(error_as, error["code"]) if error else None
    if problem:
        _fail(f"{at}/error/code", problem)
    if state == "recovery_required" and (c.get("cause") == "interrupted") != (c["error"]["code"] == "INTERRUPTED"):
        _fail(f"{at}/error/code", "recovery_required uses INTERRUPTED exactly when its cause is interrupted")


def is_transition(kind: str, source: str, target: str) -> bool:
    """True when the journal kind's table allows source -> target."""
    table = LIFECYCLE["transitions"].get(kind, {})
    return target in table.get(source, [])


def _journal_rules(j: Doc) -> None:
    checkpoints = j["checkpoints"]
    kind = j["kind"]
    initial = LIFECYCLE["initial"][kind]
    if checkpoints[0]["state"] != initial:
        noun = "legacy record" if kind == "legacy" else "transaction"
        _fail("/checkpoints/0/state", f"a {noun} starts at {initial}")
    if kind == "transaction" and j["plan_digest"] is None:
        _fail("/plan_digest", "a transaction binds its plan_digest")
    if kind == "legacy" and j["plan_digest"] is not None:
        _fail("/plan_digest", "a legacy record has no plan_digest")
    if j["generation"] < len(checkpoints):
        _fail("/generation", "generation counts durable writes and cannot be below the number of checkpoints")
    resolved = kind == "transaction" and j["action"] in RESOLVED and j["target"] is not None
    if resolved and not _is_release(j["target"]["version"]):
        _fail("/target/version", f"a {j['action']} transaction targets a resolved release, named like 0.4.7")
    attempts = 0
    for i, c in enumerate(checkpoints):
        at = f"/checkpoints/{i}"
        _checkpoint_rules(c, at)
        if i == 0:
            continue
        prev = checkpoints[i - 1]
        source = prev["state"]
        if "outcome" in prev:
            _fail(at, f"the operation was closed by an outcome at record {i - 1}; nothing may follow")
        if c["sequence"] <= prev["sequence"]:
            _fail(f"{at}/sequence", "sequences must increase")
        if c["state"] == "interrupted" and c["checkpoint"] != source:
            _fail(f"{at}/checkpoint", f"the last durable checkpoint is {source}, not {c['checkpoint']}")
        if c.get("outcome") == "manual" and source != "recovery_required":
            _fail(f"{at}/outcome", "manual closes an operation on a record that repeats its recovery_required record")
        if c["state"] == "recovering" and source != "recovering":
            attempts += 1
            if attempts > LIFECYCLE["max_recovery_attempts"]:
                _fail(
                    f"{at}/state",
                    f"recovery attempts exhausted (at most {LIFECYCLE['max_recovery_attempts']} per operation); "
                    "close it with outcome manual once resolved by hand",
                )
        if source == c["state"]:
            progress = "step" in c and c["state"] in LIFECYCLE["progress_states"]
            closing = c.get("outcome") in ("refused", "manual")
            if progress and "step" in prev:
                _fail(f"{at}/state", f"a later {c['state']} step replaces the earlier stepped record in place; it is not appended")
            if not progress and not closing:
                _fail(f"{at}/state", f"{source} -> {c['state']} repeats a state without a step")
        elif not is_transition(kind, source, c["state"]):
            _fail(f"{at}/state", f"{source} -> {c['state']} is not a {kind} transition")
        elif source == "verified" and c["state"] == "applying" and j["action"] != "install":
            _fail(f"{at}/state", "verified -> applying skips the recovery point, which only an install may do")
    if any(c["state"] == "recovery_saved" for c in checkpoints) and j["recovery"] is None:
        _fail("/recovery", "a journal past recovery_saved references its recovery point")


def _no_rules(_: Doc) -> None:
    """The history index has no cross-field rules (contract section 8)."""


KINDS: dict[str, tuple[str, Doc, Doc, Callable[[Doc], None]]] = {
    "plan": ("a plan", PLAN, PLAN["$defs"], _plan_rules),
    "event": ("an event", EVENT, EVENT["$defs"], _event_rules),
    "result": ("a result", RESULT, RESULT["$defs"], _result_rules),
    "journal": ("a journal", JOURNAL, JOURNAL["$defs"], _journal_rules),
    "history": ("a history index", RESULT["$defs"]["history_index"], RESULT["$defs"], _no_rules),
}


def _size_check(kind: str, size: int) -> None:
    label, schema, _, _ = KINDS[kind]
    if size > schema["x-max-bytes"]:
        _fail("", f"{size} bytes; {label} is at most {schema['x-max-bytes']} bytes")


def _assert_valid(kind: str, value: Json) -> None:
    label, schema, defs, rules = KINDS[kind]
    text = canonicalize(value)
    if not isinstance(value, dict):
        _fail("", f"{label} must be a JSON object")
    _size_check(kind, len(text.encode("utf-8")))
    version = value.get("schema_version", _MISSING)
    if not _same(version, SCHEMA_VERSION):
        seen = "(missing)" if version is _MISSING else _js(version)
        raise ContractError("/schema_version", f"unsupported schema_version {seen} (this build reads {SCHEMA_VERSION})", True)
    error = _check(schema, defs, value, "")
    if error:
        _fail(error[0], error[1])
    rules(value)


def validate_document(kind: str, value: Json) -> Doc:
    """Validate an in-memory document: {"ok": True} or the first refusal, as the coordinator reports it."""
    if kind not in KINDS:
        raise TypeError(f"unknown lifecycle document kind {kind!r}")
    try:
        _assert_valid(kind, value)
    except ContractError as error:
        return {"ok": False, "path": error.path, "reason": error.reason, "unsupported": error.unsupported}
    return {"ok": True}


class _Lenient(Exception):
    """A value json.loads accepts but the contract and JSON.parse do not (NaN, Infinity)."""


def _loads(text: str) -> tuple[Json, str | None]:
    """Parse as JSON.parse would; also return the first thing the coordinator's text scan refuses.

    Python reads some text more leniently than JSON.parse (NaN, Infinity) and
    silently normalizes what the scan must see (duplicate keys, 1.0, 1e3, -0),
    so the hooks refuse the first and note the second.
    """
    problems: list[str] = []
    number = "number {} is not a safe integer (no fractions, exponents, -0 or values beyond 2^53-1)"

    def pairs(items: list[tuple[str, Json]]) -> Doc:
        seen: set[str] = set()
        for key, _ in items:
            if key in seen:
                problems.append(f"duplicate key {_js(key)[:66]}")
            seen.add(key)
        return dict(items)

    def integer(token: str) -> int:
        if token == "-0" or len(token.lstrip("-")) > 16 or abs(int(token)) > MAX_SAFE:
            problems.append(number.format(token[:32]))
            return 0
        return int(token)

    def fraction(token: str) -> float:
        problems.append(number.format(token[:32]))
        return 0.0

    def constant(token: str) -> NoReturn:
        raise _Lenient(token)

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_int=integer, parse_float=fraction, parse_constant=constant)
    except (ValueError, _Lenient):
        _fail("", "is not valid JSON")
    except RecursionError:
        _fail("", f"nested deeper than {MAX_DEPTH} levels")
    return value, (problems[0] if problems else None)


def parse_document(kind: str, data: bytes) -> Doc:
    """Parse and validate one received document; the size bound applies before parsing."""
    if kind not in KINDS:
        raise TypeError(f"unknown lifecycle document kind {kind!r}")
    _size_check(kind, len(data))
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail("", "is not valid UTF-8")
    value, problem = _loads(text)
    if not isinstance(value, dict):
        _fail("", f"{KINDS[kind][0]} must be a JSON object")
    if problem:
        _fail("", problem)
    _assert_valid(kind, value)
    return value


def conforms(kind: str, name: str, value: Json) -> bool:
    """True when value matches $defs/<name> of that document kind."""
    defs = KINDS[kind][2]
    if name not in defs:
        raise TypeError(f"no $defs/{name} in the {kind} schema")
    return _check(defs[name], defs, value, "") is None


# --- Redaction (contract section 1.7).

_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_CONTROL_ON_ONE_LINE = re.compile("[\x00-\x1f\x7f-\x9f]")
_CREDENTIALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|[\s\S]*)"),
     "[redacted private key]"),
    (re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/?#@ \x00-\x1f]*:[^/?#@ \x00-\x1f]*@"), r"\g<1>[redacted]@"),
    (re.compile(r"(Bearer|bearer|BEARER) [A-Za-z0-9._~+/=-]{8,}"), r"\g<1> [redacted]"),
    (re.compile(
        r"([Pp]ass(?:word|wd)|PASS(?:WORD|WD)|[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Aa]pi_?[Kk]ey|API_?KEY|[Vv]ault_[Kk]ey|VAULT_KEY)"
        r"[ ]?[=:][ ]?(?:[=:][ ]?)?[^ \x00-\x1f]+"
    ), r"\g<1> (redacted)"),
]
_SHAPES = [_pattern(shape["pattern"]) for shape in RESULT["$defs"]["text"]["not"]["anyOf"]]
_UNREDACTABLE = "[redacted: the text looked like it held a credential]"
_CUT_SEPARATOR = re.compile(r"[ =:]+\Z")


def _credential_shaped(text: str) -> bool:
    return any(shape.search(text) for shape in _SHAPES)


def redact_text(value: str, max_length: int = 4096, single_line: bool = False) -> str:
    """Contract text from any string, exactly as lifecycle-contract.js redactText makes it."""
    text = _SURROGATE.sub("�", value)
    control = _CONTROL_ON_ONE_LINE if single_line else _CONTROL
    text = control.sub(lambda m: f"\\u{ord(m.group(0)):04x}", text)
    rounds = 0
    while rounds < 4 and _credential_shaped(text):
        for shape, mask in _CREDENTIALS:
            text = shape.sub(mask, text)
        rounds += 1
    if _credential_shaped(text):
        text = _UNREDACTABLE
    if len(text) <= max_length:
        return text
    cut = text[: max_length - 1]
    if _credential_shaped(cut + "…"):
        cut = _CUT_SEPARATOR.sub("", cut)
    return cut + "…"


# --- The state tree (contract section 10; layout of ruling R7).


class Disk:
    """The syscalls an atomic write is made of, in one place so fault-injection tests can replace them."""

    def write(self, fd: int, data: bytes) -> int:
        """os.write."""
        return os.write(fd, data)

    def fsync(self, fd: int) -> None:
        """os.fsync of a file."""
        os.fsync(fd)

    def replace(self, source: str, target: str, src_dir_fd: int, dst_dir_fd: int) -> None:
        """os.replace within one directory: the atomic step."""
        os.replace(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    def fsync_dir(self, fd: int) -> None:
        """os.fsync of a directory, which makes a rename durable."""
        os.fsync(fd)


DISK = Disk()
_OPEN_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_PLAIN_PATH = re.compile(r"(/[A-Za-z0-9._@+-]+)+\Z")
_OPERATION = _pattern(JOURNAL["$defs"]["operation_id"]["pattern"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _trusted_uids() -> set[int]:
    euid = os.geteuid()
    return {0} if euid == 0 else {0, euid}


def state_root() -> str:
    """The fixed root, or CB_LIFECYCLE_ROOT for an unprivileged test over a disposable root (ruling R8)."""
    seam = os.environ.get("CB_LIFECYCLE_ROOT", "")
    if not seam:
        return DEFAULT_ROOT
    if os.geteuid() == 0:
        raise StateError(
            "USAGE", f"CB_LIFECYCLE_ROOT is a test seam and is refused as root; the state root is always {DEFAULT_ROOT}"
        )
    if len(seam) > 1024 or not _PLAIN_PATH.match(seam) or "/./" in seam + "/" or "/../" in seam + "/":
        raise StateError("USAGE", "CB_LIFECYCLE_ROOT must be a plain absolute path")
    return seam


def _check_node(st: os.stat_result, where: str, role: str) -> None:
    """Refuse (6) a state path with an untrusted owner, the wrong type or a loose mode."""
    if st.st_uid not in _trusted_uids():
        raise StateError("PERMISSION", f"{where} is owned by uid {st.st_uid}, which is not trusted with lifecycle state")
    perm = stat.S_IMODE(st.st_mode)
    want_file = role in ("lock", "file")
    if want_file != stat.S_ISREG(st.st_mode) or (not want_file and not stat.S_ISDIR(st.st_mode)):
        raise StateError("PERMISSION", f"{where} is not a {'regular file' if want_file else 'directory'}")
    if role == "ancestor" and perm & 0o022 and not (perm & 0o1000 and st.st_uid == 0):
        raise StateError("PERMISSION", f"{where} is writable by group or others")
    if role == "root" and perm & 0o022:
        raise StateError("PERMISSION", f"{where} is writable by group or others")
    if role == "private" and perm & 0o777 != 0o700:
        raise StateError("PERMISSION", f"{where} must be mode 0700 (it is {perm:04o})")
    if role in ("lock", "file") and perm != 0o600:
        raise StateError("PERMISSION", f"{where} must be mode 0600 (it is {perm:04o})")
    if role == "lock" and st.st_nlink != 1:
        raise StateError("PERMISSION", f"{where} has more than one name")


def _open_dir(name: str, parent: int | None, where: str, role: str) -> int | None:
    """Open one directory without following a symlink and check it; None when it does not exist."""
    try:
        fd = os.open(name, _OPEN_DIR, dir_fd=parent)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise StateError("PERMISSION", f"{where} is a symbolic link or not a directory; refusing to use it") from None
        if error.errno == errno.EACCES:
            raise StateError("PERMISSION", f"permission denied: cannot enter {where}") from None
        raise StateError("PREFLIGHT", f"cannot open {where}: {error.strerror}") from None
    try:
        _check_node(os.fstat(fd), where, role)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _make_private_dir(name: str, parent: int) -> None:
    """mkdir 0700 whatever the umask; an existing entry is left for the caller's checks."""
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
    except FileExistsError:
        return
    fd = os.open(name, _OPEN_DIR, dir_fd=parent)
    try:
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


class Tree:
    """Open, validated descriptors of the state root and its private directory."""

    def __init__(self, path: str, root: int, private: int) -> None:
        self.path = path
        self.root = root
        self.private = private
        self.operations: int | None = None

    def close(self) -> None:
        """Close every descriptor this tree holds."""
        for fd in (self.operations, self.private, self.root):
            if fd is not None:
                os.close(fd)

    def open_operations(self, create: bool) -> int | None:
        """The private operations directory, created 0700 when asked and missing."""
        if self.operations is None:
            where = f"{self.path}/private/operations"
            fd = _open_dir("operations", self.private, where, "private")
            if fd is None and create:
                try:
                    _make_private_dir("operations", self.private)
                except OSError as error:
                    raise StateError("PREFLIGHT", f"cannot create {where}: {error.strerror}") from None
                DISK.fsync_dir(self.private)
                fd = _open_dir("operations", self.private, where, "private")
            self.operations = fd
        return self.operations


def open_tree() -> Tree | None:
    """Validate every ancestor, the root and private/ (ruling R8); None when the root does not exist yet."""
    path = state_root()
    parts = path.strip("/").split("/")
    fd = os.open("/", _OPEN_DIR)
    where = ""
    try:
        _check_node(os.fstat(fd), "/", "ancestor")
        for i, part in enumerate(parts):
            where = f"{where}/{part}"
            role = "root" if i == len(parts) - 1 else "ancestor"
            child = _open_dir(part, fd, where, role)
            os.close(fd)
            fd = -1
            if child is None:
                return None
            fd = child
        private = _open_dir("private", fd, f"{path}/private", "private")
        if private is None:
            os.close(fd)
            return None
        return Tree(path, fd, private)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        raise


# --- Lock ownership (ruling R9): a write needs the descriptor that holds the lock.

_OWNER_SHAPES = {
    "pid": re.compile(r"[1-9][0-9]{0,9}\Z"),
    "start": re.compile(r"[0-9]{1,20}\Z"),
    "label": re.compile(r"[a-z][a-z0-9._-]*( [a-z0-9][a-z0-9._-]*){0,3}\Z"),
    "since": re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z"),
    "operation": _OPERATION,
}


def read_owner(tree: Tree) -> dict[str, str]:
    """The lock owner record: each line matched against its own shape, nothing evaluated."""
    owner: dict[str, str] = {}
    try:
        fd = os.open("owner", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=tree.private)
    except OSError:
        return owner
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return owner
        raw = os.read(fd, 1024)
    finally:
        os.close(fd)
    for line in raw.decode("utf-8", errors="replace").splitlines()[:8]:
        key, _, value = line.partition("=")
        shape = _OWNER_SHAPES.get(key)
        if shape is not None and shape.match(value) and (key != "operation" or valid_operation_id(value)):
            owner[key] = value
    return owner


def valid_operation_id(value: Json) -> bool:
    """op-YYYYMMDD-NNN with a real calendar date."""
    return isinstance(value, str) and _OPERATION.search(value) is not None and FORMATS["cb-operation-id"](value)


def _start_ticks(pid: str) -> str | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            raw = handle.read().decode("ascii", errors="replace")
    except OSError:
        return None
    fields = raw[raw.rfind(")") + 2:].split()
    return fields[19] if len(fields) > 19 else None


def require_lock(tree: Tree) -> str:
    """Prove CB_LIFECYCLE_LOCK_FD holds the host lock; returns the operation the lock is bound to ("" when none)."""
    raw = os.environ.get("CB_LIFECYCLE_LOCK_FD", "")
    missing = StateError("USAGE", "a state write needs the host lifecycle lock held through CB_LIFECYCLE_LOCK_FD")
    if not re.fullmatch(r"[1-9][0-9]{0,4}", raw) or int(raw) < 3:
        raise missing
    fd = int(raw)
    try:
        held = os.fstat(fd)
        lock = os.stat("lock", dir_fd=tree.private, follow_symlinks=False)
    except OSError:
        raise missing from None
    _check_node(lock, f"{tree.path}/private/lock", "lock")
    if (held.st_dev, held.st_ino) != (lock.st_dev, lock.st_ino):
        raise missing
    probe = os.open("lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=tree.private)
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            # A fresh description took it, so nobody held it, and the inherited one held nothing.
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise missing
    finally:
        os.close(probe)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise missing from None
    bound = os.environ.get("CB_LIFECYCLE_OPERATION", "")
    if bound and not valid_operation_id(bound):
        raise StateError("USAGE", "CB_LIFECYCLE_OPERATION is not an operation ID")
    if read_owner(tree).get("operation", "") != bound:
        raise StateError("USAGE", "CB_LIFECYCLE_OPERATION is not the operation the host lock is bound to")
    return bound


# --- Atomic records.


def _random_suffix() -> str:
    return os.urandom(6).hex()


def write_atomic(dir_fd: int, name: str, data: bytes, mode: int) -> None:
    """Write `name` in dir_fd through a same-directory temporary file: write, fsync, rename, fsync the directory."""
    temp = f".{name}.{_random_suffix()}"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=dir_fd)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[DISK.write(fd, bytes(view)):]
        DISK.fsync(fd)
    except BaseException:
        os.close(fd)
        _unlink_quietly(dir_fd, temp)
        raise
    os.close(fd)
    try:
        DISK.replace(temp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        _unlink_quietly(dir_fd, temp)
        raise
    DISK.fsync_dir(dir_fd)


def _unlink_quietly(dir_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dir_fd)
    except OSError:
        pass


def _write_failure(what: str, error: OSError) -> StateError:
    detail = "the disk is full" if error.errno in (errno.ENOSPC, errno.EDQUOT, errno.EFBIG) else error.strerror
    return StateError(
        "PREFLIGHT",
        f"cannot record {what} durably ({detail}); nothing was acknowledged, so stop before the next change",
    )


def _remove_leftovers(dir_fd: int, prefixes: Iterable[str]) -> None:
    """Remove temporaries a crashed writer left; only a lock holder writes, so none is live."""
    for name in os.listdir(dir_fd):
        if name.startswith(tuple(prefixes)):
            _unlink_quietly(dir_fd, name)


def _remove_staging(operations: int, name: str) -> None:
    """Remove a begin's staging directory that was never renamed into place (it was never acknowledged)."""
    try:
        fd = os.open(name, _OPEN_DIR, dir_fd=operations)
    except OSError:
        return
    try:
        for entry in os.listdir(fd):
            _unlink_quietly(fd, entry)
    finally:
        os.close(fd)
    try:
        os.rmdir(name, dir_fd=operations)
    except OSError:
        pass


# --- Reading records.


class Record:
    """One entry of private/operations: a journal, or a record that requires inspection."""

    def __init__(self, name: str, journal: Doc | None = None, reason: str = "", unsupported: bool = False) -> None:
        self.name = name
        self.journal = journal
        self.reason = reason
        self.unsupported = unsupported


def _read_bounded(fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size < limit:
        chunk = os.read(fd, limit - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def read_record(operations: int, name: str, base: str) -> Record:
    """Read and validate one operation's journal; any doubt makes it a record that requires inspection."""
    where = f"{base}/{name}"
    if not valid_operation_id(name):
        return Record(name, reason="is not an operation directory")
    try:
        fd = os.open(name, _OPEN_DIR, dir_fd=operations)
    except OSError as error:
        return Record(name, reason=f"cannot be opened as a directory ({error.strerror})")
    try:
        try:
            _check_node(os.fstat(fd), where, "private")
            jfd = os.open("journal.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        except StateError as error:
            return Record(name, reason=error.message)
        except FileNotFoundError:
            return Record(name, reason="has no journal")
        except OSError as error:
            return Record(name, reason=f"journal cannot be opened ({error.strerror})")
        try:
            try:
                _check_node(os.fstat(jfd), f"{where}/journal.json", "file")
            except StateError as error:
                return Record(name, reason=error.message)
            data = _read_bounded(jfd, KINDS["journal"][1]["x-max-bytes"] + 1)
        finally:
            os.close(jfd)
    finally:
        os.close(fd)
    try:
        journal = parse_document("journal", data)
    except ContractError as error:
        return Record(name, reason=f"journal {error}", unsupported=error.unsupported)
    if journal["operation_id"] != name:
        return Record(name, reason=f"journal names another operation ({journal['operation_id']})")
    return Record(name, journal=journal)


def read_records(tree: Tree) -> list[Record]:
    """Every entry of private/operations, in name order; temporaries and staging are skipped."""
    operations = tree.open_operations(create=False)
    if operations is None:
        return []
    base = f"{tree.path}/private/operations"
    return [read_record(operations, name, base) for name in sorted(os.listdir(operations)) if not name.startswith(".")]


def last(journal: Doc) -> Doc:
    """The journal's last checkpoint."""
    checkpoints: list[Doc] = journal["checkpoints"]
    return checkpoints[-1]


def finished(journal: Doc) -> bool:
    """A journal whose last record carries an outcome."""
    return "outcome" in last(journal)


def in_progress(journal: Doc) -> bool:
    """Unfinished and not settled into recovery_required or a post-mutation interrupted record."""
    return not finished(journal) and last(journal)["state"] not in ("recovery_required", "interrupted")


# --- Requests (contract section 10).

_TEXT = "text"
_INT = "int"
_REQUESTS: dict[str, dict[str, tuple[str, bool]]] = {
    "inspect": {"operation_id": ("operation_id", True)},
    "list": {},
    "begin": {
        "kind": ("kind", True),
        "action": ("journal_action", True),
        "adapter": ("adapter", True),
        "plan_digest": ("digest", False),
        "identity_digest": ("digest", False),
        "source_version": (_TEXT, False),
        "source_artifact_digest": ("digest", False),
        "target_version": (_TEXT, False),
        "target_artifact_digest": ("digest", False),
        "recovery_operation_id": ("operation_id", False),
        "recovery_manifest_digest": ("digest", False),
        "evidence_check": ("evidence_check", False),
        "evidence_result": ("evidence_result", False),
        "evidence_detail": (_TEXT, False),
    },
    "checkpoint": {
        "operation_id": ("operation_id", True),
        "expected_generation": (_INT, True),
        "state": ("state", True),
        "step": ("step", False),
        "cause": ("cause", False),
        "outcome": ("outcome", False),
        "error_code": ("exit_name", False),
        "error_reason": (_TEXT, False),
        "recovery_operation_id": ("operation_id", False),
        "recovery_manifest_digest": ("digest", False),
        "evidence_check": ("evidence_check", False),
        "evidence_result": ("evidence_result", False),
        "evidence_detail": (_TEXT, False),
    },
}
_RECORD_PROPS: Doc = JOURNAL["properties"]["checkpoints"]["items"]["properties"]
_EVIDENCE_PROPS: Doc = JOURNAL["properties"]["evidence"]["items"]["properties"]
_MEMBER_NODES: dict[str, Doc] = {
    "operation_id": {"$ref": "#/$defs/operation_id"},
    "kind": {"$ref": "#/$defs/kind"},
    "journal_action": {"$ref": "#/$defs/journal_action"},
    "adapter": {"$ref": "#/$defs/adapter"},
    "digest": {"$ref": "#/$defs/digest"},
    "state": {"$ref": "#/$defs/state"},
    "step": _RECORD_PROPS["step"],
    "cause": _RECORD_PROPS["cause"],
    "outcome": _RECORD_PROPS["outcome"],
    "exit_name": {"$ref": "#/$defs/exit_name"},
    "evidence_check": _EVIDENCE_PROPS["check"],
    "evidence_result": _EVIDENCE_PROPS["result"],
}


def read_request(stream: BinaryIO) -> Doc:
    """One bounded, closed JSON request from stdin."""
    data = stream.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        raise StateError("USAGE", f"a request is at most {MAX_REQUEST_BYTES} bytes")
    try:
        if not data.strip():
            raise ContractError("", "is empty")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _fail("", "is not valid UTF-8")
        value, problem = _loads(text)
        if not isinstance(value, dict):
            _fail("", "must be a JSON object")
        if problem:
            _fail("", problem)
        canonicalize(value)
    except ContractError as error:
        raise StateError("USAGE", f"the request {error}") from None
    name = value.get("request")
    if not isinstance(name, str) or name not in _REQUESTS:
        raise StateError("USAGE", "request must be one of " + ", ".join(sorted(_REQUESTS)))
    members = _REQUESTS[name]
    for key, item in value.items():
        if key == "request":
            continue
        if key not in members:
            if _SECRET_NAME.search(key):
                raise StateError("USAGE", f"{key} looks like a secret field; a {name} request carries none")
            raise StateError("USAGE", f"{key} is not a member of a {name} request")
        shape, _required = members[key]
        if item is None and not _required:
            continue
        if shape == _TEXT:
            ok = isinstance(item, str) and len(item) <= MAX_REQUEST_TEXT
        elif shape == _INT:
            ok = _type_of(item) == "integer" and 1 <= item <= MAX_SAFE
        else:
            ok = _check(_MEMBER_NODES[shape], JOURNAL["$defs"], item, "") is None
        if not ok:
            raise StateError("USAGE", f"{key} is not a valid {shape.replace('_', ' ')}")
    for key, (_, required) in members.items():
        if required and value.get(key) is None:
            raise StateError("USAGE", f"a {name} request needs {key}")
    return value


def _version(request: Doc, key: str, kind: str) -> str | None:
    """J11: an installed version kept exactly; a legacy producer records null for one that is not one."""
    value = request.get(key)
    if value is None or conforms("journal", "installed_version", value):
        return value
    if kind == "legacy":
        return None
    raise StateError("USAGE", f"{key} is not an installed version (1-64 characters, no control character)")


def _evidence(request: Doc) -> Doc | None:
    check, result = request.get("evidence_check"), request.get("evidence_result")
    if check is None and result is None and request.get("evidence_detail") is None:
        return None
    if check is None or result is None:
        raise StateError("USAGE", "evidence needs evidence_check and evidence_result")
    detail = request.get("evidence_detail")
    return {"check": check, "result": result, "detail": None if detail is None else redact_text(detail, 256)}


def _recovery(request: Doc) -> Doc | None:
    ref_id, digest = request.get("recovery_operation_id"), request.get("recovery_manifest_digest")
    if ref_id is None and digest is None:
        return None
    if ref_id is None or digest is None:
        raise StateError("USAGE", "a recovery reference needs recovery_operation_id and recovery_manifest_digest")
    return {"operation_id": ref_id, "manifest_digest": digest}


def _release(version: str | None, digest: str | None) -> Doc | None:
    if version is None:
        return None
    return {"version": version, "artifact_digest": digest}


def _valid_or_usage(kind: str, document: Doc) -> None:
    result = validate_document(kind, document)
    if not result["ok"]:
        raise StateError("USAGE", f"the record would break the lifecycle contract: {result['path']}: {result['reason']}")


def _checkpoint_event(journal: Doc) -> str:
    record = last(journal)
    event = {
        "schema_version": SCHEMA_VERSION,
        "operation_id": journal["operation_id"],
        "sequence": record["sequence"],
        "at": record["at"],
        "source": "native",
        "type": "checkpoint",
        "state": record["state"],
        "generation": journal["generation"],
    }
    _valid_or_usage("event", event)
    return canonicalize(event)


# --- The sequence counter (ruling R15): one per operation, shared with its events.


def _read_counter(op_fd: int) -> int:
    try:
        fd = os.open("sequence", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=op_fd)
    except OSError:
        return 0
    try:
        raw = os.read(fd, 32).decode("ascii", errors="replace").strip()
    finally:
        os.close(fd)
    return int(raw) if re.fullmatch(r"[1-9][0-9]{0,15}", raw) else 0


def _next_sequence(op_fd: int, journal: Doc) -> int:
    """Above both the counter and the journal's durable sequence, so a lost counter never repeats one."""
    durable = max(int(c["sequence"]) for c in journal["checkpoints"])
    return max(_read_counter(op_fd), durable) + 1


# --- The history index (contract section 8) and retention.

_FILE_NAME = RESULT["$defs"]["file_name"]


def _summary(journal: Doc) -> Doc:
    record = last(journal)
    source, target = journal["source"], journal["target"]
    return {
        "inspection_required": False,
        "operation_id": journal["operation_id"],
        "kind": journal["kind"],
        "action": journal["action"],
        "adapter": journal["adapter"],
        "state": record["state"],
        "outcome": record.get("outcome"),
        "checkpoint": record.get("checkpoint"),
        "started_at": journal["started_at"],
        "updated_at": journal["updated_at"],
        "source_version": None if source is None else source["version"],
        "target_version": None if target is None else target["version"],
        "recovery_available": journal["recovery"] is not None,
    }


def display_name(name: str) -> str:
    """A directory entry's name as printable text on one line.

    os.listdir hands back a name that is not UTF-8 with its bytes as lone
    surrogates, which no record, line or index may carry: those bytes, and any
    character that is not printable, are shown as backslash escapes instead.
    """
    text = os.fsencode(name).decode("utf-8", "backslashreplace")
    return "".join(c if c.isprintable() else ascii(c)[1:-1] for c in text)


def _inspection(record: Record) -> Doc:
    shown = display_name(record.name)
    name = record.name if shown == record.name and _check(_FILE_NAME, RESULT["$defs"], record.name, "") is None else None
    reason = redact_text(f"{shown}: {record.reason}", 256)
    return {"inspection_required": True, "record": name, "reason": reason}


def build_index(records: list[Record]) -> tuple[Doc, int]:
    """The index: unfinished operations, then records that require inspection, then the newest finished ones."""
    journals = [r.journal for r in records if r.journal is not None]
    unfinished = sorted((j for j in journals if not finished(j)), key=lambda j: (j["started_at"], j["operation_id"]), reverse=True)
    closed = sorted((j for j in journals if finished(j)), key=lambda j: (j["updated_at"], j["operation_id"]), reverse=True)
    entries = [_summary(j) for j in unfinished]
    entries += [_inspection(r) for r in records if r.journal is None]
    entries += [_summary(j) for j in closed]
    limit = RESULT["$defs"]["history_index"]["properties"]["operations"]["maxItems"]
    index = {"schema_version": SCHEMA_VERSION, "generated_at": _now(), "operations": entries[:limit]}
    _valid_or_usage("history", index)
    return index, max(0, len(entries) - limit)


def write_index(tree: Tree, records: list[Record]) -> int:
    """Atomically replace history.json (0644, redacted, derived); returns how many entries it left out."""
    index, omitted = build_index(records)
    _remove_leftovers(tree.root, [".history.json."])
    write_atomic(tree.root, "history.json", (canonicalize(index) + "\n").encode("utf-8"), 0o644)
    return omitted


def retention(records: list[Record]) -> tuple[list[str], list[str], bool]:
    """Recovery references that must be kept, those no record needs, and whether the answer is complete.

    Kept: every reference an unfinished operation holds, and the newest point
    recorded by an operation that committed (the last successful point). A
    record that requires inspection might hold any reference, so while one
    exists nothing is releasable.
    """
    journals = [r.journal for r in records if r.journal is not None]

    def ref(journal: Doc) -> str:
        return f"{journal['recovery']['operation_id']}:{journal['recovery']['manifest_digest']}"

    held = [j for j in journals if j["recovery"] is not None]
    protected = {ref(j) for j in held if not finished(j)}
    committed = sorted((j for j in held if last(j).get("outcome") == "committed"), key=lambda j: (j["updated_at"], j["operation_id"]))
    if committed:
        protected.add(ref(committed[-1]))
    complete = all(r.journal is not None for r in records)
    releasable = sorted({ref(j) for j in held} - protected) if complete else []
    return sorted(protected), releasable, complete


# --- Reconciliation: the next lock holder persists what a killed process could not (ruling R5).


def _abandon(tree: Tree, record: Record) -> tuple[Record, str | None]:
    """Close a killed operation's in-progress journal with an `interrupted` record (cause abandoned)."""
    journal = record.journal
    assert journal is not None
    operations = tree.open_operations(create=False)
    assert operations is not None
    previous = last(journal)
    stamp = _now()
    try:
        op_fd = os.open(record.name, _OPEN_DIR, dir_fd=operations)
    except OSError as error:
        return record, f"{record.name}: cannot record its interruption ({error.strerror})"
    try:
        entry: Doc = {"sequence": _next_sequence(op_fd, journal), "state": "interrupted", "at": stamp,
                      "cause": "abandoned", "checkpoint": previous["state"]}
        if previous["state"] in LIFECYCLE["pre_mutation"]:
            entry["outcome"] = "interrupted"
        updated = dict(journal, checkpoints=journal["checkpoints"] + [entry], generation=journal["generation"] + 1,
                       updated_at=stamp)
        if not validate_document("journal", updated)["ok"]:
            return record, f"{record.name}: its process is gone, and its journal has no legal interrupted record"
        _remove_leftovers(op_fd, [".journal.json.", ".sequence."])
        write_atomic(op_fd, "sequence", f"{entry['sequence']}\n".encode("ascii"), 0o600)
        write_atomic(op_fd, "journal.json", (canonicalize(updated) + "\n").encode("utf-8"), 0o600)
    except OSError as error:
        raise _write_failure(f"the interruption of {record.name}", error) from None
    finally:
        os.close(op_fd)
    return Record(record.name, journal=updated), None


def reconcile(tree: Tree, records: list[Record], bound: str) -> tuple[list[Record], list[str]]:
    """Persist `interrupted` for every in-progress operation other than the one the lock is bound to."""
    result: list[Record] = []
    warnings: list[str] = []
    for record in records:
        if record.journal is not None and record.name != bound and in_progress(record.journal):
            record, warning = _abandon(tree, record)
            if warning:
                warnings.append(warning)
        result.append(record)
    return result, warnings


# --- The four requests.


def _lines(**values: Any) -> list[str]:
    return [f"{key}={value}" for key, value in values.items()]


def _warning_lines(warnings: Iterable[str]) -> list[str]:
    return ["warning=" + redact_text(w, 900, single_line=True) for w in warnings]


def _locked_tree() -> tuple[Tree, str]:
    tree = open_tree()
    if tree is None:
        raise StateError("USAGE", "a state write needs the host lifecycle lock held through CB_LIFECYCLE_LOCK_FD")
    try:
        return tree, require_lock(tree)
    except BaseException:
        tree.close()
        raise


def _status(tree: Tree, journal: Doc) -> str:
    if finished(journal):
        return "finished"
    if not in_progress(journal):
        return "unfinished"
    owner = read_owner(tree)
    alive = "pid" in owner and _start_ticks(owner["pid"]) == owner.get("start")
    return "running" if alive and owner.get("operation") == journal["operation_id"] else "abandoned"


def handle_inspect(request: Doc) -> list[str]:
    """Report one operation's durable state; reads only, needs no lock."""
    op = request["operation_id"]
    tree = open_tree()
    if tree is None:
        raise StateError("USAGE", f"no operation {op} exists (there is no lifecycle state yet)")
    try:
        operations = tree.open_operations(create=False)
        if operations is None or op not in os.listdir(operations):
            raise StateError("USAGE", f"no operation {op} exists")
        record = read_record(operations, op, f"{tree.path}/private/operations")
        if record.journal is None:
            reason = redact_text(record.reason, 256, single_line=True)
            raise StateError("UNSUPPORTED" if record.unsupported else "MANUAL",
                             f"{op} requires inspection: {reason}", ["inspection_required=yes", f"reason={reason}"])
        journal = record.journal
        status = _status(tree, journal)
        record_last = last(journal)
        return _lines(
            operation_id=op, kind=journal["kind"], action=journal["action"], state=record_last["state"],
            generation=journal["generation"], sequence=record_last["sequence"], status=status,
            reported="interrupted" if status == "abandoned" else record_last["state"],
            outcome=record_last.get("outcome", ""), checkpoint=record_last.get("checkpoint", ""),
            journal=canonicalize(journal),
        )
    finally:
        tree.close()


def _today_ids(names: Iterable[str], day: str) -> int:
    highest = 0
    for name in names:
        match = re.fullmatch(r"op-" + day + r"-([0-9]{3,9})", name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest


def handle_begin(request: Doc) -> list[str]:
    """Allocate an operation ID under the lock and write its first durable record."""
    kind = request["kind"]
    tree, bound = _locked_tree()
    try:
        if bound:
            raise StateError("USAGE", f"the host lock is bound to {bound} already; one lock holds one operation")
        operations = tree.open_operations(create=True)
        assert operations is not None
        for name in os.listdir(operations):
            if name.startswith(".new-"):
                _remove_staging(operations, name)
        records, warnings = reconcile(tree, read_records(tree), bound)
        blocking = [r.name for r in records if r.journal is not None and r.journal["kind"] == "transaction" and not finished(r.journal)]
        doubtful = [r for r in records if r.journal is None]
        if kind == "transaction" and doubtful:
            blocking += [display_name(r.name) for r in doubtful]
        else:
            warnings += [f"{display_name(r.name)} requires inspection: {r.reason}" for r in doubtful]
        warnings += [f"{r.name} ({r.journal['action']}) is unfinished" for r in records
                     if r.journal is not None and r.journal["kind"] == "legacy" and not finished(r.journal)]
        if blocking:
            _index_quietly(tree, lambda: records)
            raise StateError("MANUAL", "an unfinished lifecycle operation must be reconciled first: " + ", ".join(blocking[:5]),
                             _warning_lines(warnings))
        stamp = _now()
        day = stamp[:10].replace("-", "")
        number = _today_ids(os.listdir(operations), day) + 1
        if number > 999_999_999:
            raise StateError("PREFLIGHT", "no operation ID is left for today")
        op = f"op-{day}-{number:03d}"
        journal: Doc = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": op,
            "kind": kind,
            "action": request["action"],
            "adapter": request["adapter"],
            "generation": 1,
            "plan_digest": request.get("plan_digest"),
            "identity_digest": request.get("identity_digest"),
            "source": _release(_version(request, "source_version", kind), request.get("source_artifact_digest")),
            "target": _release(_version(request, "target_version", kind), request.get("target_artifact_digest")),
            "recovery": _recovery(request),
            "evidence": [e for e in [_evidence(request)] if e is not None],
            "started_at": stamp,
            "updated_at": stamp,
            "checkpoints": [{"sequence": 1, "state": LIFECYCLE["initial"][kind], "at": stamp}],
        }
        _valid_or_usage("journal", journal)
        event = _checkpoint_event(journal)
        staging = f".new-{_random_suffix()}"
        try:
            os.mkdir(staging, 0o700, dir_fd=operations)
            stage_fd = os.open(staging, _OPEN_DIR, dir_fd=operations)
            os.fchmod(stage_fd, 0o700)
            try:
                write_atomic(stage_fd, "sequence", b"1\n", 0o600)
                write_atomic(stage_fd, "journal.json", (canonicalize(journal) + "\n").encode("utf-8"), 0o600)
            finally:
                os.close(stage_fd)
            DISK.replace(staging, op, src_dir_fd=operations, dst_dir_fd=operations)
            DISK.fsync_dir(operations)
        except OSError as error:
            _remove_staging(operations, staging)
            raise _write_failure(f"operation {op}", error) from None
        records.append(Record(op, journal=journal))
        warnings += _index_quietly(tree, lambda: records)
        return _lines(operation_id=op, generation=1, sequence=1, state=LIFECYCLE["initial"][kind]) + _warning_lines(warnings) + [f"event={event}"]
    finally:
        tree.close()


def _index_quietly(tree: Tree, records: Callable[[], list[Record]]) -> list[str]:
    """Rewrite the index after a durable write; the journal is authoritative, so a failure only warns.

    Once a record is durable the request has succeeded: nothing the index does,
    reading the records again included, may turn that into a failure the
    caller would take for an unwritten record.
    """
    try:
        current = records()
        omitted = write_index(tree, current)
    except OSError as error:
        return [f"history.json was not updated ({error.strerror}); the journals are intact"]
    except StateError as error:
        return [f"history.json was not updated ({error.message}); the journals are intact"]
    return [f"history.json lists the first {len(current) - omitted} operations"] if omitted else []


def handle_checkpoint(request: Doc) -> list[str]:
    """Append (or, for a later step, replace) one durable record of the operation the lock is bound to."""
    op = request["operation_id"]
    tree, bound = _locked_tree()
    try:
        if bound != op:
            raise StateError("USAGE", f"the host lock is bound to {bound or 'no operation'}, not {op}")
        operations = tree.open_operations(create=False)
        if operations is None or op not in os.listdir(operations):
            raise StateError("USAGE", f"no operation {op} exists")
        record = read_record(operations, op, f"{tree.path}/private/operations")
        if record.journal is None:
            reason = redact_text(record.reason, 256, single_line=True)
            raise StateError("UNSUPPORTED" if record.unsupported else "MANUAL", f"{op} requires inspection: {reason}")
        journal = record.journal
        if request["expected_generation"] != journal["generation"]:
            raise StateError(
                "MANUAL",
                f"{op} is at generation {journal['generation']}, not {request['expected_generation']}: "
                "another writer recorded a checkpoint since, so this one is stale; inspect it before changing anything",
            )
        op_fd = os.open(op, _OPEN_DIR, dir_fd=operations)
        try:
            updated, entry = _next_journal(op_fd, journal, request)
            event = _checkpoint_event(updated)
            _remove_leftovers(op_fd, [".journal.json.", ".sequence."])
            try:
                write_atomic(op_fd, "sequence", f"{entry['sequence']}\n".encode("ascii"), 0o600)
                write_atomic(op_fd, "journal.json", (canonicalize(updated) + "\n").encode("utf-8"), 0o600)
            except OSError as error:
                raise _write_failure(f"the {entry['state']} checkpoint of {op}", error) from None
        finally:
            os.close(op_fd)
        warnings = _index_quietly(tree, lambda: [r if r.name != op else Record(op, journal=updated) for r in read_records(tree)])
        return _lines(operation_id=op, generation=updated["generation"], sequence=entry["sequence"],
                      state=entry["state"]) + _warning_lines(warnings) + [f"event={event}"]
    finally:
        tree.close()


def _next_journal(op_fd: int, journal: Doc, request: Doc) -> tuple[Doc, Doc]:
    previous = last(journal)
    stamp = _now()
    entry: Doc = {"sequence": _next_sequence(op_fd, journal), "state": request["state"], "at": stamp}
    for key in ("step", "cause", "outcome"):
        if request.get(key) is not None:
            entry[key] = request[key]
    if request["state"] == "interrupted":
        entry["checkpoint"] = previous["state"]
    code, reason = request.get("error_code"), request.get("error_reason")
    if (code is None) != (reason is None):
        raise StateError("USAGE", "an error needs error_code and error_reason")
    if code is not None:
        entry["error"] = {"code": code, "reason": redact_text(str(reason), 256)}
    checkpoints = list(journal["checkpoints"])
    stepped = "step" in entry and "step" in previous and previous["state"] == entry["state"]
    if stepped:
        checkpoints[-1] = entry
    else:
        checkpoints.append(entry)
    recovery = journal["recovery"]
    wanted = _recovery(request)
    if wanted is not None:
        if recovery is not None and recovery != wanted:
            raise StateError("USAGE", f"{journal['operation_id']} references another recovery point already")
        recovery = wanted
    evidence = list(journal["evidence"])
    item = _evidence(request)
    if item is not None:
        evidence.append(item)
    updated = dict(journal, checkpoints=checkpoints, generation=journal["generation"] + 1,
                   updated_at=stamp, recovery=recovery, evidence=evidence)
    _valid_or_usage("journal", updated)
    return updated, entry


def handle_list(_: Doc) -> list[str]:
    """Persist abandoned operations, rewrite history.json and report what retention must keep."""
    tree, bound = _locked_tree()
    try:
        operations = tree.open_operations(create=True)
        assert operations is not None
        records, warnings = reconcile(tree, read_records(tree), bound)
        try:
            omitted = write_index(tree, records)
        except OSError as error:
            raise _write_failure("history.json", error) from None
        protected, releasable, complete = retention(records)
        lines = _lines(operations=len(records), indexed=len(records) - omitted, omitted=omitted)
        lines += [f"unfinished={r.name}" for r in records if r.journal is not None and not finished(r.journal)]
        lines += [f"inspection={display_name(r.name)}" for r in records if r.journal is None]
        lines += [f"protected={ref}" for ref in protected] + [f"releasable={ref}" for ref in releasable]
        lines += [f"retention={'complete' if complete else 'blocked'}"]
        return lines + _warning_lines(warnings)
    finally:
        tree.close()


HANDLERS: dict[str, Callable[[Doc], list[str]]] = {
    "inspect": handle_inspect,
    "begin": handle_begin,
    "checkpoint": handle_checkpoint,
    "list": handle_list,
}


def run(stdin: BinaryIO, stdout: Callable[[str], object], stderr: Callable[[str], object]) -> int:
    """Serve one request; returns the lifecycle exit code."""
    try:
        request = read_request(stdin)
        lines = HANDLERS[request["request"]](request)
    except StateError as error:
        for line in error.lines:
            stdout(line + "\n")
        stderr("lifecycle state: " + redact_text(error.message, 900, single_line=True) + "\n")
        return EXIT[error.code]
    for line in lines:
        stdout(line + "\n")
    return EXIT["OK"]


def main() -> int:
    """Entry point: signals are ignored so a request is never cut in half; the caller's trap acts after it."""
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, signal.SIG_IGN)
    os.umask(0o077)
    if sys.stdin.isatty():
        sys.stderr.write("lifecycle state: reads one JSON request on stdin\n")
        return EXIT["USAGE"]
    try:
        code = run(sys.stdin.buffer, sys.stdout.write, sys.stderr.write)
        sys.stdout.flush()
    except BrokenPipeError:
        return EXIT["PREFLIGHT"]
    return code


if __name__ == "__main__":
    sys.exit(main())
