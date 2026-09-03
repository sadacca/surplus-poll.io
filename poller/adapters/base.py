"""Adapter interface: one implementation per surplus/auction site (FR5)."""

from __future__ import annotations

from typing import Protocol

from poller.models import Listing, Query


class SiteError(Exception):
    """Raised by an adapter on timeout, non-200 response, or parse failure."""


class Adapter(Protocol):
    """A site adapter turns a Query into a list of matching Listings."""

    name: str

    def search(self, query: Query) -> list[Listing]: ...
