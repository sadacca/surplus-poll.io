"""Core data models: search Query config and a matched Listing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Query:
    """One search definition loaded from queries.yaml."""

    id: str
    label: str
    enabled: bool
    sites: tuple[str, ...]
    keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...] = ()
    category: str | None = None
    max_price: float | None = None
    state: str | None = None
    zip: str | None = None
    radius_miles: float | None = None
    notify: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Listing:
    """A single listing returned by a site adapter."""

    site: str
    listing_id: str
    title: str
    url: str
    price: float | None = None
    bid_count: int | None = None
    thumbnail_url: str | None = None
    end_time: str | None = None
    location: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Dedup key: (site, listing_id), per FR12."""
        return (self.site, self.listing_id)


@dataclass(frozen=True, slots=True)
class Match:
    """A Listing paired with the Query that matched it, for notification."""

    listing: Listing
    query: Query
