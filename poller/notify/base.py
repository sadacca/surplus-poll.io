"""Notifier interface: one implementation per notification channel (FR15)."""

from __future__ import annotations

from typing import Protocol

from poller.models import Match


class NotifyError(Exception):
    """Raised when a notifier fails to deliver after its retry policy."""


class Notifier(Protocol):
    """A notifier sends a batch of matches to one channel (FR16)."""

    name: str

    def send(self, matches: list[Match]) -> None: ...
