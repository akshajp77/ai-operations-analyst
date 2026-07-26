"""Pydantic schemas — the public API shape.

Naming convention, applied consistently so the generated TypeScript client
reads predictably:

* ``XCreate``   — request body for creation
* ``XUpdate``   — request body for partial update (every field optional)
* ``XRead``     — full representation returned to a client
* ``XSummary``  — trimmed representation used in list endpoints

The summary/read split is a deliberate performance decision, not tidiness: a
dataset list must not serialise every column profile for fifty datasets.
"""
