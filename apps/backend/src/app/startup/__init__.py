"""Startup-path modules split out of ``app.main``.

``main`` is the composition root: it creates the app, includes routers and
attaches the lifespan.  The work the lifespan *does* — schema checks, Alembic,
scheduled-job registration, first-run seeding — lives here so that changing any
of it does not mean editing the same file every router change touches.

Nothing in this package is imported for its side effects; ``main`` calls into it.
"""
