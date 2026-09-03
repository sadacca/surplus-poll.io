"""Test doubles shared across the test suite."""

from __future__ import annotations

from poller.adapters.base import SiteError
from poller.models import Listing, Query


class FakeAdapter:
    """An in-memory Adapter for orchestrator tests. No network access."""

    def __init__(self, name: str, listings: list[Listing] | None = None, error: str | None = None):
        self.name = name
        self._listings = listings or []
        self._error = error
        self.calls: list[Query] = []

    def search(self, query: Query) -> list[Listing]:
        self.calls.append(query)
        if self._error:
            raise SiteError(self._error)
        return list(self._listings)
