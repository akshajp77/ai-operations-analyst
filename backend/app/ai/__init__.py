"""The AI reasoning layer. The only package permitted to call a model.

Centralising every model call in one package is what makes cost, latency,
prompt versions, and failure behaviour governable. If model calls were
scattered across services, none of those would be.

Planned modules:

* ``client.py``     — a thin, typed wrapper over the OpenAI Responses API:
  timeouts, bounded retries with jitter, token accounting, and translation of
  provider errors into ``AIProviderError``.
* ``prompts/``      — prompt templates as versioned files, not inline strings.
  A prompt is behaviour; it belongs under review and in the diff like any
  other logic.
* ``narrative.py``  — turns ``Finding`` objects into an executive summary.
* ``recommendations.py`` — turns findings into ranked, actionable advice.
* ``schemas.py``    — Pydantic models for structured model output.

**The rule that makes this trustworthy:** the model never sees the raw
dataset and never produces a number. It receives computed
``app.analytics.contracts.Finding`` objects — each already carrying its
evidence — and returns prose plus references to those findings. Any figure in
the final report is traceable to arithmetic in ``app/analytics``.

That constraint delivers three things at once: hallucinated statistics become
structurally impossible; customer data is minimised at the third-party
boundary, which matters for the compliance conversation every enterprise
buyer will start; and token cost stays proportional to the number of findings
rather than to the size of the upload.

**Graceful degradation.** A model outage must not fail an analysis. Services
catch ``AIProviderError`` and return the deterministic results with the
narrative marked unavailable. The charts and numbers — the part the customer
paid for — still render.
"""
