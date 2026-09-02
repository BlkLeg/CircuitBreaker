"""Scheduled jobs extracted from the lifespan (route F9).

`main.py` registers 29 jobs, ten of which were closures defined inline in the
lifespan. Those ten are the ones F9 is about: a closure nested in a 2,500-line
startup function cannot be imported, so it cannot be unit tested, and the only
way to exercise its error handling is to boot the application.

Modules here hold extracted job bodies verbatim. Extraction is incremental by
design — the route says "do incrementally, jobs first" — so this package starts
with the Proxmox batch and the rest stay inline until they are moved with the
same care.
"""
