"""Cross-cutting concerns: configuration, logging, errors, middleware.

Everything in this package is infrastructure that every other layer may
depend on. The dependency arrow points *inward only*: ``core`` must never
import from ``api``, ``services``, ``models``, or ``analytics``. Enforcing
that keeps the import graph acyclic and makes ``core`` safe to use from a
worker or a script with no web server present.
"""
