"""Values every model module needs.

``_now`` is the default and onupdate callable on nearly every timestamp column,
and the two foreign-key strings are the ones typed most often. They live here
rather than in one of the model modules so that the model modules never import
each other: the only cross-module reference in this package is to this file.
"""

from datetime import datetime

from app.core.time import utcnow


def _now() -> datetime:
    return utcnow()


_FK_HARDWARE_ID = "hardware.id"
_FK_SERVICES_ID = "services.id"
