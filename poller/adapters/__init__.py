"""Adapter registry. Adding a new site = one adapter module + one line here."""

from __future__ import annotations

from poller.adapters.base import Adapter
from poller.http import RateLimitedClient

ADAPTERS: dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    ADAPTERS[adapter.name] = adapter


def register_builtin_adapters(clients: dict[str, RateLimitedClient]) -> None:
    """Instantiate and register the shipped site adapters.

    `clients` maps site name -> RateLimitedClient, so each adapter gets its
    own rate limiter (FR7). Called once at process startup by poller.__main__.
    """
    from poller.adapters.publicsurplus import PublicSurplusAdapter

    if "publicsurplus" in clients:
        register(PublicSurplusAdapter(clients["publicsurplus"]))
