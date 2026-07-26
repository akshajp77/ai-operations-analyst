"""Deterministic analytics engines. The product's source of truth.

Everything in this package is a pure function of its inputs: no database, no
network, no model calls. See ``contracts.py`` for why that constraint exists
and what it buys.

Planned modules, each satisfying ``contracts.AnalysisEngine``:

* ``profiling.py`` — one pass over the data producing a ``DatasetProfile``.
  Runs first; every other engine reads its output.
* ``cleaning.py``  — type coercion, whitespace and encoding repair, duplicate
  detection, missing-value strategy. Returns a cleaned frame *and* a record
  of every change, because silent cleaning is how you lose a customer's
  trust.
* ``quality.py``   — completeness, validity, consistency, uniqueness scoring.
* ``trends.py``    — direction, magnitude, and change points over time.
* ``forecast.py``  — projection with explicit confidence intervals.
* ``anomaly.py``   — points and periods that deviate from expectation.
* ``registry.py``  — ordered engine registration and orchestration.

**Engine choice.** Polars is the default: multi-threaded, lazily optimised,
and far more predictable in memory than pandas on wide frames. DuckDB handles
anything SQL-shaped — grouped aggregations, joins across uploaded files, and
larger-than-memory scans — because expressing those as SQL is clearer than
chaining forty dataframe operations. pandas stays at the edges, where a
statistics or forecasting library requires it. Conversions go through Arrow,
so they are zero-copy rather than a serialisation tax.
"""
