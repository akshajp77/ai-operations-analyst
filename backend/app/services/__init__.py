"""Application services: use-case orchestration.

A service answers "what happens when a user does X?" and is the only layer
that coordinates across the others:

    route (HTTP)  ->  service (orchestration)  ->  { repository | analytics | ai | storage }

Rules:

* A service receives an ``AsyncSession``; it never opens or commits a
  transaction. The dependency that provided the session owns that boundary,
  which is what makes "one request, one transaction" actually hold.
* A service raises domain errors from ``app.core.exceptions``. It never
  imports ``fastapi`` — that would couple business logic to a transport and
  make it unusable from a worker.
* A service returns domain objects or Pydantic schemas, never ORM rows still
  attached to a session the caller does not control.

Planned services: ``dataset_service`` (upload, parse, profile, persist),
``analysis_service`` (run engines, assemble results), ``report_service``
(compose narrative and recommendations, render artefacts).
"""
