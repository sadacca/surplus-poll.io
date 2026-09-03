"""Slack webhook notifier (FR10, FR14, FR16)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

import requests

from poller.models import Match
from poller.notify import register

logger = logging.getLogger(__name__)

WEBHOOK_URL_ENV_VAR = "SLACK_WEBHOOK_URL"
# Slack caps a message at 50 blocks; each match uses 2 (section + divider).
MAX_MATCHES_PER_MESSAGE = 24
BETWEEN_MESSAGE_DELAY_SECONDS = 1.0


class SlackNotifier:
    name = "slack"

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
        for i in range(0, len(matches), MAX_MATCHES_PER_MESSAGE):
            chunk = matches[i : i + MAX_MATCHES_PER_MESSAGE]
            self._post({"blocks": _to_blocks(chunk)})
            if i + MAX_MATCHES_PER_MESSAGE < len(matches):
                self._sleep(BETWEEN_MESSAGE_DELAY_SECONDS)

    def _post(self, payload: dict) -> None:
        response = self.session.post(self.webhook_url, json=payload, timeout=(10, 30))
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            logger.warning("slack: rate limited, retrying after %.1fs", retry_after)
            self._sleep(retry_after)
            response = self.session.post(self.webhook_url, json=payload, timeout=(10, 30))

        if response.status_code >= 300:
            logger.error(
                "slack: webhook post failed with %d: %s", response.status_code, response.text
            )


def _to_blocks(matches: list[Match]) -> list[dict]:
    blocks: list[dict] = []
    for match in matches:
        listing = match.listing
        lines = [f"*<{listing.url}|{listing.title}>*", f"{match.query.label} · {listing.site}"]
        if listing.price is not None:
            price_text = f"${listing.price:,.2f}"
            if listing.bid_count is not None:
                price_text += f" ({listing.bid_count} bids)"
            lines.append(price_text)

        section: dict = {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(lines)},
        }
        if listing.thumbnail_url:
            section["accessory"] = {
                "type": "image",
                "image_url": listing.thumbnail_url,
                "alt_text": listing.title,
            }
        blocks.append(section)
        blocks.append({"type": "divider"})

    if blocks:
        blocks.pop()  # drop the trailing divider
    return blocks


def _build_from_env() -> SlackNotifier | None:
    webhook_url = os.environ.get(WEBHOOK_URL_ENV_VAR)
    if not webhook_url:
        return None
    return SlackNotifier(webhook_url)


register("slack", _build_from_env)
