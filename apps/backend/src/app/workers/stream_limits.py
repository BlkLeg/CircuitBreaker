"""Retro-fit stream limits onto a JetStream stream that already exists.

This lives here, shared, rather than once per worker, because having it twice is
what produced regression R12 and then let half of it survive the fix.

`add_stream` against a stream whose stored config differs reports "stream name
already in use" -- the same string an identical stream never produces. A worker
that swallows that keeps whatever limitless stream it was first created with,
forever, and never sees a byte of the bounding fix (B15). So the mismatch branch
has to reach back and update the stream in place.

STREAM.UPDATE is a *replace*, not a patch. The request body is a whole
StreamConfig, and `nats.js.api.Base.as_dict()` silently drops every field still
set to None -- so a field this build has no opinion about is not "left alone" by
the server, it arrives as zero and JetStream substitutes its own default.
Sending only the desired config therefore reset `num_replicas` to 1 and
re-derived `storage`, which on a clustered NATS demotes an R3 stream to R1 on the
first worker boot after an upgrade, with no error and no log line to say the
redundancy is gone. That is R12. The update is consequently built from the
*server's* copy of the config, with only the fields this build actually wants to
change laid over the top.

Four things a maintainer must not undo:

1. Read every field off the stored config rather than an allow-list of the ones
   we happen to care about today. An allow-list is how this broke the first time,
   and the next field JetStream grows would be re-defaulted the same way.
2. Keep taking the retention policy from the server. JetStream refuses an update
   that changes retention and rejects the whole request when it sees one, so
   sending WorkQueuePolicy at a stream created under LimitsPolicy would throw the
   max_age/max_bytes fix away along with it. Existing installs therefore stay
   LimitsPolicy and merely become bounded -- which is the part that actually
   closes the disk-exhaustion path; only streams created from scratch get the
   work queue.
3. Keep the dedupe window clamped to `max_age`. See the comment on that line.
4. Keep both workers calling THIS function. TELEMETRY and DISCOVERY had
   byte-identical copies of the broken expression; only one was fixed, and the
   asymmetry was invisible until someone drove the other through nats-py's own
   serializer. One implementation cannot drift from itself.
"""

from __future__ import annotations

import logging
from dataclasses import fields as dataclass_fields
from typing import Any

from nats.js.api import StreamConfig

_logger = logging.getLogger(__name__)

# The full set of fields to copy forward from the server's stored config. Derived
# from the dataclass rather than typed out, so the list cannot fall behind a
# nats-py upgrade the way a hand-written one would.
#
# The ceiling is nats-py's model of the config, not the server's, and the
# difference matters to whoever reads this next: `Base.from_response` drops
# response keys it does not model, so a config field a newer nats-server grows
# before the pinned client learns about it never reaches `info.config` and is
# re-defaulted by exactly the mechanism the echo below exists to stop. Bumping
# nats-py is what closes that gap; this list only follows it.
_STREAM_CONFIG_FIELDS = tuple(f.name for f in dataclass_fields(StreamConfig))


async def update_stream_limits(js: Any, cfg: dict[str, Any]) -> None:
    """Lay `cfg`'s limits over the server's stored config for the stream it names."""
    name = cfg["name"]
    try:
        info = await js.stream_info(name)
        stored = {field: getattr(info.config, field, None) for field in _STREAM_CONFIG_FIELDS}
        # None means "the server did not report this one", which is the one case
        # where omitting it from the body is correct -- there is nothing to preserve.
        update = {field: value for field, value in stored.items() if value is not None}
        # Everything except retention, which stays whatever the server already has.
        update.update({field: value for field, value in cfg.items() if field != "retention"})
        # Echoing the stored config means the body now carries `duplicate_window`,
        # which the pre-R12 body never sent, and that one field can cost the whole
        # request. JetStream refuses an update whose dedupe window is longer than its
        # max_age (err_code=10052) instead of clamping it, and nats-server stamps its
        # 120s default on every stream created without an opinion on dedupe -- which
        # is every stream this retrofit exists for. So with a max_age under 120 the
        # update is rejected whole, the rejection lands in the `except` below as a
        # warning nobody reads, and the stream keeps max_age=0/max_bytes=-1 forever,
        # since every later boot fails identically. That is B15's disk-exhaustion
        # path, reopened by the fix for R12. Shrinking the window to fit is the only
        # outcome the server accepts, and it is the cheap side of the trade: a
        # publisher retrying more than max_age later may be seen twice, against an
        # unbounded stream as the alternative. max_age == 0 is JetStream's "no age
        # limit" and constrains nothing, so leave the window alone there.
        max_age = update.get("max_age") or 0
        if max_age > 0 and (update.get("duplicate_window") or 0) > max_age:
            update["duplicate_window"] = max_age
        await js.update_stream(**update)
        _logger.info("NATS %s stream limits updated", name)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("NATS %s stream limits update failed: %s", name, exc)
