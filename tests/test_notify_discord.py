import json

import responses

from poller.models import Listing, Match, Query
from poller.notify.discord import DiscordNotifier, _build_from_env

WEBHOOK = "https://discord.com/api/webhooks/123/abc"


def make_match(listing_id="1", price=100.0, bid_count=2, title="GPU"):
    q = Query(
        id="gpu-search",
        label="Server GPUs",
        enabled=True,
        sites=("publicsurplus",),
        keywords=("gpu",),
    )
    listing = Listing(
        site="publicsurplus",
        listing_id=listing_id,
        title=title,
        url=f"http://x/{listing_id}",
        price=price,
        bid_count=bid_count,
        thumbnail_url="http://x/thumb.jpg",
    )
    return Match(listing=listing, query=q)


@responses.activate
def test_send_empty_matches_posts_nothing():
    notifier = DiscordNotifier(WEBHOOK)
    notifier.send([])
    assert len(responses.calls) == 0


@responses.activate
def test_send_single_batch_under_limit():
    responses.add(responses.POST, WEBHOOK, status=204)
    notifier = DiscordNotifier(WEBHOOK)
    notifier.send([make_match("1"), make_match("2")])

    assert len(responses.calls) == 1
    payload = json.loads(responses.calls[0].request.body)
    assert len(payload["embeds"]) == 2
    assert payload["embeds"][0]["title"] == "GPU"
    assert payload["embeds"][0]["url"] == "http://x/1"
    assert payload["embeds"][0]["thumbnail"]["url"] == "http://x/thumb.jpg"


@responses.activate
def test_send_splits_into_multiple_messages_over_ten_embeds():
    responses.add(responses.POST, WEBHOOK, status=204)
    responses.add(responses.POST, WEBHOOK, status=204)
    sleeps = []
    notifier = DiscordNotifier(WEBHOOK, sleep=sleeps.append)

    matches = [make_match(str(i)) for i in range(12)]
    notifier.send(matches)

    assert len(responses.calls) == 2
    first_payload = json.loads(responses.calls[0].request.body)
    second_payload = json.loads(responses.calls[1].request.body)
    assert len(first_payload["embeds"]) == 10
    assert len(second_payload["embeds"]) == 2
    assert sleeps == [1.0]


@responses.activate
def test_price_and_bid_count_rendered_in_embed():
    responses.add(responses.POST, WEBHOOK, status=204)
    notifier = DiscordNotifier(WEBHOOK)
    notifier.send([make_match("1", price=1234.5, bid_count=7)])

    payload = json.loads(responses.calls[0].request.body)
    price_field = next(f for f in payload["embeds"][0]["fields"] if f["name"] == "Price")
    assert price_field["value"] == "$1,234.50 (7 bids)"


@responses.activate
def test_429_retries_once_after_retry_after_header():
    responses.add(responses.POST, WEBHOOK, status=429, headers={"Retry-After": "2.5"})
    responses.add(responses.POST, WEBHOOK, status=204)
    sleeps = []
    notifier = DiscordNotifier(WEBHOOK, sleep=sleeps.append)

    notifier.send([make_match("1")])

    assert len(responses.calls) == 2
    assert sleeps == [2.5]


def test_factory_returns_none_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert _build_from_env() is None


def test_factory_returns_notifier_when_env_var_set(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    notifier = _build_from_env()
    assert notifier is not None
    assert notifier.webhook_url == WEBHOOK
