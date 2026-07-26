"""Pagination primitives shared by every collection endpoint.

Defined once, centrally, because pagination is the classic API inconsistency:
without a shared type you end up with ``?page=``, ``?offset=``, and
``?cursor=`` across three endpoints and a frontend that special-cases each.

We expose **offset pagination** here. It is the right default for this
product: result sets are per-tenant and bounded (a customer has hundreds of
datasets, not millions), and users expect to jump to a page. When a listing
grows unbounded — audit events, row-level anomalies — add a cursor variant
alongside this rather than reworking it, since the two have genuinely
different semantics.
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, Field

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """Query parameters for a paginated listing.

    Used as a FastAPI dependency so the contract appears in OpenAPI — and
    therefore in the generated TypeScript client — automatically::

        @router.get("/datasets")
        async def list_datasets(page: Annotated[PageParams, Depends()]) -> Page[Dataset]:
            ...
    """

    page: Annotated[int, Field(ge=1, description="1-based page number.")] = 1
    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_PAGE_SIZE,
            description=f"Items per page (max {MAX_PAGE_SIZE}).",
        ),
    ] = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        """Rows to skip — the value handed to SQL ``OFFSET``."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """Rows to fetch — the value handed to SQL ``LIMIT``."""
        return self.page_size


class PageMeta(BaseModel):
    """Pagination metadata returned alongside every page of results."""

    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


class Page[ItemT](BaseModel):
    """A single page of results.

    Generic so that ``Page[DatasetSummary]`` produces a precise OpenAPI schema
    and, downstream, a precise TypeScript type — rather than an opaque
    ``items: unknown[]`` the frontend has to cast.

    Uses PEP 695 type-parameter syntax, which is available from Python 3.12 —
    our pinned runtime — and scopes ``ItemT`` to this class instead of leaking
    a module-level ``TypeVar``.
    """

    items: list[ItemT]
    meta: PageMeta

    @classmethod
    def create(cls, items: list[ItemT], total_items: int, params: PageParams) -> Self:
        """Build a page from a result slice and its unpaginated total.

        Args:
            items: The rows for this page (already limited/offset in SQL).
            total_items: Total matching rows, ignoring pagination.
            params: The parameters that produced ``items``.
        """
        # Ceiling division without importing math; a total of 0 yields 0 pages
        # rather than 1, so an empty collection reads as genuinely empty.
        total_pages = -(-total_items // params.page_size) if total_items else 0
        return cls(
            items=items,
            meta=PageMeta(
                page=params.page,
                page_size=params.page_size,
                total_items=total_items,
                total_pages=total_pages,
                has_next=params.page < total_pages,
                has_previous=params.page > 1,
            ),
        )
