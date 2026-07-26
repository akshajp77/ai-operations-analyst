"""Contracts for the analytics layer.

This module is the most important architectural boundary in the product, so
it is worth stating the rule plainly:

    **Analytics is pure. It takes data in and returns findings out.**
    No database. No HTTP. No OpenAI. No side effects that matter.

Everything downstream depends on that purity:

* **Testability.** An engine is tested with a hand-built frame and an
  assertion. No fixtures, no containers, no network, no mocks.
* **Determinism.** The same input always produces the same findings, so a
  regression is a real change in behaviour rather than model drift.
* **Trust.** Every number a user sees is computed here, by code we can point
  at. The language model *narrates* these findings; it never invents them.
  That single constraint is what separates an analyst from a plausible-sounding
  text generator, and it is enforced structurally — the AI layer receives
  :class:`Finding` objects, never a raw dataset.
* **Reuse.** The same engine runs inside a request, a background job, or a
  notebook.

Engines are composed through the :class:`AnalysisEngine` protocol. Adding
"seasonality detection" means adding one module that satisfies the protocol
and registering it — no existing engine, service, or route changes. That is
the open/closed principle doing real work rather than appearing on a slide.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    # Imported for typing only. Keeping the heavy dataframe import out of the
    # runtime path means `app.core` and `app.api` can import these contracts
    # without paying Polars' import cost.
    import polars as pl


class Severity(StrEnum):
    """How much a finding should demand the reader's attention.

    Ordered deliberately: the report generator sorts by this, and the UI maps
    it to colour. Keeping the vocabulary small stops every engine inventing
    its own scale.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Direction(StrEnum):
    """Which way a metric moved."""

    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class ColumnRole(StrEnum):
    """The semantic role a column plays in an operational dataset.

    Inferred once during profiling and reused by every engine, so the
    forecaster does not re-derive "which column is the date" and disagree with
    the trend engine about it.
    """

    TIMESTAMP = "timestamp"
    METRIC = "metric"  # numeric, additive: revenue, units, minutes
    DIMENSION = "dimension"  # categorical: region, sku, channel
    IDENTIFIER = "identifier"  # high-cardinality key: order_id
    TEXT = "text"  # free text: notes
    UNKNOWN = "unknown"


class ColumnProfile(BaseModel):
    """Descriptive statistics for one column.

    Computed once, then reused. Profiling is the expensive pass over the data;
    every engine reading from a shared profile instead of rescanning is the
    difference between one pass and eight.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    dtype: str = Field(description="Physical type as reported by the dataframe engine.")
    role: ColumnRole = ColumnRole.UNKNOWN

    row_count: int
    null_count: int
    distinct_count: int

    # Populated for numeric columns only.
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    std_dev: float | None = None

    # Populated for timestamp columns only.
    earliest: datetime | date | None = None
    latest: datetime | date | None = None

    sample_values: list[str] = Field(
        default_factory=list,
        description="A handful of stringified examples, used for AI column "
        "labelling and for the UI preview. Bounded in size on purpose.",
    )

    @property
    def null_fraction(self) -> float:
        """Share of missing values, from 0.0 to 1.0."""
        return self.null_count / self.row_count if self.row_count else 0.0

    @property
    def is_constant(self) -> bool:
        """A single distinct value carries no information for analysis."""
        return self.distinct_count <= 1


class DatasetProfile(BaseModel):
    """Everything an engine needs to know about a dataset before running.

    Passing this rather than the raw frame lets an engine answer "can I run at
    all?" cheaply — a forecaster with no timestamp column should decline in
    microseconds, not after loading ten million rows.
    """

    model_config = ConfigDict(frozen=True)

    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    memory_bytes: int | None = None

    def column(self, name: str) -> ColumnProfile | None:
        return next((column for column in self.columns if column.name == name), None)

    def columns_with_role(self, role: ColumnRole) -> list[ColumnProfile]:
        return [column for column in self.columns if column.role == role]


class Evidence(BaseModel):
    """The numbers behind a finding.

    Every finding must carry its evidence. This is what makes the eventual
    report auditable: a user who does not believe a claim can see the value,
    the comparison, and the window it was computed over. It is also the only
    thing the AI layer is given to narrate, which keeps its output tethered to
    arithmetic rather than to plausibility.
    """

    model_config = ConfigDict(frozen=True)

    metric: str = Field(description="Human-readable name of what was measured.")
    value: float
    unit: str | None = None

    baseline: float | None = Field(
        default=None,
        description="The value being compared against, if this is a comparison.",
    )
    change_ratio: float | None = Field(
        default=None,
        description="(value - baseline) / baseline, when a baseline exists.",
    )
    direction: Direction | None = None

    window_start: datetime | date | None = None
    window_end: datetime | date | None = None

    # Free-form, engine-specific numbers (p-values, confidence bounds, model
    # coefficients). Deliberately loose: constraining it would force every
    # engine into the same statistical vocabulary.
    extra: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    """One thing the system observed about the data.

    A finding is a *fact*, not a recommendation. "Order volume fell 23% in the
    last 14 days" is a finding. "Increase staffing" is a recommendation,
    derived later from one or more findings. Keeping them as separate types
    stops the deterministic layer from smuggling in opinions, and makes the
    recommendation layer's reasoning explicit and reviewable.
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(
        description="Stable machine-readable identifier, e.g. 'trend.decline'. "
        "The UI keys off this for icons and drill-downs, so it must not "
        "change once released."
    )
    title: str = Field(description="One line, plain English, no jargon.")
    detail: str = Field(description="A short paragraph a non-analyst can follow.")
    severity: Severity = Severity.INFO

    columns: list[str] = Field(
        default_factory=list,
        description="Columns this finding concerns, for UI highlighting.",
    )
    evidence: list[Evidence] = Field(default_factory=list)

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="How much the engine trusts this result. A forecast from "
        "eight data points is reported honestly as low-confidence rather than "
        "suppressed — the user decides what to do with a weak signal.",
    )


class AnalysisResult(BaseModel):
    """What one engine produced for one dataset."""

    model_config = ConfigDict(frozen=True)

    engine: str
    findings: list[Finding] = Field(default_factory=list)
    duration_ms: float | None = None

    # An engine that could not run is not an error. "Not enough history to
    # forecast" is a legitimate, reportable outcome, and the orchestrator must
    # be able to continue with the other engines.
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def highest_severity(self) -> Severity:
        """Severity of the most serious finding, or INFO when there are none."""
        order = list(Severity)
        return max(
            (finding.severity for finding in self.findings),
            key=order.index,
            default=Severity.INFO,
        )


@runtime_checkable
class AnalysisEngine(Protocol):
    """The contract every analysis engine satisfies.

    A :class:`~typing.Protocol` rather than an abstract base class, on
    purpose. Structural typing means an engine does not inherit from us — it
    simply has the right shape. That keeps engines independently testable,
    lets a test substitute a three-line stub, and avoids the inheritance
    hierarchy these plugin systems otherwise grow.

    Implementations must be **stateless**. Any per-run state lives in local
    variables, so one instance is safe to reuse across concurrent analyses.
    """

    @property
    def name(self) -> str:
        """Stable identifier, e.g. ``"trend"``. Appears in results and logs."""
        ...

    def applies_to(self, profile: DatasetProfile) -> bool:
        """Cheaply decide whether this engine can say anything useful.

        Must not touch the data — only the profile. Returning False here is
        how an engine declines without the orchestrator needing to know
        anything about its requirements.
        """
        ...

    def run(self, frame: pl.DataFrame, profile: DatasetProfile) -> AnalysisResult:
        """Analyse the data and return findings.

        Must be pure with respect to its arguments: no mutation of ``frame``,
        no I/O, no reliance on wall-clock time or unseeded randomness. Raise
        :class:`app.core.exceptions.AnalysisError` for a genuine failure;
        return a skipped result for "not applicable".
        """
        ...
