"""Discord webhook notifier (FR10, FR14, FR16)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

import requests

from poller.models import Match
from poller.notify import register
from poller.notify.base import NotifyError

logger = logging.getLogger(__name__)

WEBHOOK_URL_ENV_VAR = "DISCORD_WEBHOOK_URL"
MAX_EMBEDS_PER_MESSAGE = 10
BETWEEN_MESSAGE_DELAY_SECONDS = 1.0


class DiscordNotifier:
    name = "discord"

    def __init__(
        self,
        webhook_url: str,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.webhook_url = webhook_url
        self.session = session or requests.Session()
        self._sleep = sleep

    def send(self, matches: list[Match]) -> None:
        if not matches:
            return
        embeds = [_to_embed(m) for m in matches]
        for i in range(0, len(embeds), MAX_EMBEDS_PER_MESSAGE):
            chunk = embeds[i : i + MAX_EMBEDS_PER_MESSAGE]
            self._post({"embeds": chunk})
            if i + MAX_EMBEDS_PER_MESSAGE < len(embeds):
                self._sleep(BETWEEN_MESSAGE_DELAY_SECONDS)

    def send_text(self, content: str) -> None:
        """Send a plain-text message, for health/adapter-status alerts."""
        self._post({"content": content})

    def _post(self, payload: dict) -> None:
        response = self.session.post(self.webhook_url, json=payload, timeout=(10, 30))
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            logger.warning("discord: rate limited, retrying after %.1fs", retry_after)
            self._sleep(retry_after)
            response = self.session.post(self.webhook_url, json=payload, timeout=(10, 30))

        if response.status_code >= 300:
            logger.error(
                "discord: webhook post failed with %d: %s", response.status_code, response.text
            )
            raise NotifyError(f"discord webhook post failed with {response.status_code}")


def _to_embed(match: Match) -> dict:
    listing = match.listing
    embed: dict = {
        "title": listing.title[:256],
        "url": listing.url,
        "fields": [
            {"name": "Query", "value": match.query.label, "inline": True},
            {"name": "Site", "value": listing.site, "inline": True},
        ],
    }
    if listing.price is not None:
        price_text = f"${listing.price:,.2f}"
        if listing.bid_count is not None:
            price_text += f" ({listing.bid_count} bids)"
        embed["fields"].append({"name": "Price", "value": price_text, "inline": True})
    if listing.thumbnail_url:
        embed["thumbnail"] = {"url": listing.thumbnail_url}
    return embed


def _build_from_env() -> DiscordNotifier | None:
    webhook_url = os.environ.get(WEBHOOK_URL_ENV_VAR)
    if not webhook_url:
        return None
    return DiscordNotifier(webhook_url)


register("discord", _build_from_env)
