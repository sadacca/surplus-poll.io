"""Adapter registry. Adding a new site = one adapter module + one line here."""

from __future__ import annotations

from poller.adapters.base import Adapter

ADAPTERS: dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    ADAPTERS[adapter.name] = adapter
