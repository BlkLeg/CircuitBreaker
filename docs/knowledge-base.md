# Knowledge Base

The knowledge base holds two operator-editable lookup tables that discovery
consults when naming devices. They supplement the curated `device_db.json`
shipped with Circuit Breaker.

**Where:** Settings → Knowledge Base. Admin only.

## The two tables

| Table | Keyed by | Feeds |
|---|---|---|
| MAC OUI Prefixes | The first six hex characters of a MAC address | Vendor, device type, and OS family for a discovered host |
| Hostname Patterns | A pattern plus a match type | The same three hints, from a host's reported name |

## Learned vs manual entries

Entries marked **learned** were inferred during scans; **manual** entries were
added here. `Seen` and `Last seen` are how you judge whether a learned entry is
worth trusting — a prefix seen hundreds of times across recent scans is
well-evidenced, one seen twice a month ago is not.

Source cannot be changed. Correcting a learned entry's vendor leaves it marked
learned; that is deliberate, so provenance survives the correction.

## Editing

Vendor, device type, and OS family are editable in place — click the cell.

The prefix and the pattern are identity and cannot be renamed: the API has no
rename operation, so an apparent rename would be a create plus a delete with
different provenance. Delete and re-add if you need to change one.

Match type on a hostname pattern is one of `prefix`, `exact`, or `contains`,
and is edited through the row's form rather than in place, because a free-text
value outside that set would be silently ignored by the matcher.

## Adding a MAC prefix

Enter the OUI in any conventional form — `B8:27:EB`, `b8-27-eb`, `B827EB`, or a
full MAC, from which the first six characters are taken. It is stored as six
uppercase hex characters.

## Export

**Export JSON** downloads the table in the same shape as `device_db.json`'s
`mac_oui_prefixes` / `hostname_patterns` sections, suitable for review or for
copying into another install by hand.

There is no import in 1.0 — entries are added through this screen or learned
during discovery.

## See also

- [Discovery](discovery.md) — where these hints are applied
