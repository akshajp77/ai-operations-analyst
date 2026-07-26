"""Pagination arithmetic.

Off-by-one errors in pagination are the classic bug that reaches production:
they only appear on the last page, and the last page is exactly what manual
testing skips.
"""

from __future__ import annotations

import pytest

from app.core.pagination import MAX_PAGE_SIZE, Page, PageParams

pytestmark = pytest.mark.unit


class TestPageParams:
    def test_first_page_starts_at_zero_offset(self) -> None:
        assert PageParams(page=1, page_size=25).offset == 0

    def test_offset_advances_by_page_size(self) -> None:
        assert PageParams(page=3, page_size=20).offset == 40

    def test_page_size_is_capped(self) -> None:
        """An uncapped page_size lets one request scan the whole table."""
        with pytest.raises(ValueError, match="less than or equal"):
            PageParams(page_size=MAX_PAGE_SIZE + 1)

    def test_page_is_one_based(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal"):
            PageParams(page=0)


class TestPage:
    def test_reports_total_pages_with_a_partial_last_page(self) -> None:
        page = Page.create(items=[1, 2, 3], total_items=23, params=PageParams(page=3, page_size=10))
        assert page.meta.total_pages == 3

    def test_exact_multiple_does_not_add_an_empty_page(self) -> None:
        page = Page.create(items=[], total_items=20, params=PageParams(page=2, page_size=10))
        assert page.meta.total_pages == 2

    def test_empty_collection_has_zero_pages(self) -> None:
        """Zero pages, not one — an empty list should read as genuinely empty."""
        page = Page.create(items=[], total_items=0, params=PageParams())
        assert page.meta.total_pages == 0
        assert page.meta.has_next is False
        assert page.meta.has_previous is False

    def test_navigation_flags_on_a_middle_page(self) -> None:
        page = Page.create(items=[1], total_items=100, params=PageParams(page=2, page_size=10))
        assert page.meta.has_next is True
        assert page.meta.has_previous is True

    def test_last_page_has_no_next(self) -> None:
        page = Page.create(items=[1], total_items=21, params=PageParams(page=3, page_size=10))
        assert page.meta.has_next is False
        assert page.meta.has_previous is True

    def test_preserves_item_types(self) -> None:
        page: Page[str] = Page.create(items=["a", "b"], total_items=2, params=PageParams())
        assert page.items == ["a", "b"]
