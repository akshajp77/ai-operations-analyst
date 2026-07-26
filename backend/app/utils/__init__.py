"""Small, dependency-free helpers.

A deliberately restricted package. "Utils" is where architecture goes to die:
it attracts anything that does not obviously belong elsewhere, and within a
year it imports from every layer and nothing can be tested in isolation.

Two rules keep it honest:

1. A module here may import from the standard library and third-party
   packages only — never from ``app.services``, ``app.models``, ``app.api``,
   or ``app.db``.
2. If a helper has one caller, it lives with that caller. It moves here when
   the second caller appears, not in anticipation of one.
"""
