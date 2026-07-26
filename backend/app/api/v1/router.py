"""Aggregate router for API version 1.

Every versioned route is mounted here, and this router is mounted once in
``app/main.py`` under ``/api/v1``. Versioning is by URL prefix because it is
the most legible option for the people integrating with us — the version is
visible in a log line, a curl command, and a browser address bar.

When v2 arrives it becomes a sibling package. The two versions can then share
services while presenting different schemas, which is the entire reason the
HTTP layer is kept thin.
"""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter()

# Feature routers are registered here as they land. Each `tag` becomes a
# section of the OpenAPI document and therefore a namespace in the generated
# TypeScript client:
#
# from app.api.v1.routes import analyses, datasets, reports
#
# api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
# api_router.include_router(analyses.router, prefix="/analyses", tags=["analyses"])
# api_router.include_router(reports.router,  prefix="/reports",  tags=["reports"])
