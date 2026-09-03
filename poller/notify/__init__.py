"""Notifier registry. Adding a new channel = one module + one line here."""

from __future__ import annotations

import logging
from collections.abc import Callable

from poller.notify.base import Notifier

logger = logging.getLogger(__name__)

# A factory returns None when its webhook env var isn't configured.
NotifierFactory = Callable[[], Notifier | None]

NOTIFIER_FACTORIES: dict[str, NotifierFactory] = {}


def register(channel: str, factory: NotifierFactory) -> None:
    NOTIFIER_FACTORIES[channel] = factory


def build_notifiers(channels: set[str]) -> dict[str, Notifier]:
    """Instantiate a notifier for each requested channel that is configured.

    A channel with no registered factory, or whose webhook env var is unset,
    is logged and skipped rather than failing the run.
    """
    notifiers: dict[str, Notifier] = {}
    for channel in channels:
        factory = NOTIFIER_FACTORIES.get(channel)
        if factory is None:
            logger.warning("unknown notification channel %r; skipping", channel)
            continue
        notifier = factory()
        if notifier is None:
            logger.warning(
                "channel %r has no webhook configured; matches routed there will not be sent",
                channel,
            )
            continue
        notifiers[channel] = notifier
    return notifiers
