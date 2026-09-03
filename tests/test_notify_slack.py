import json

import responses

from poller.models import Listing, Match, Query
from poller.notify.slack import SlackNotifier, _build_from_env

WEBHOOK = "https://hooks.slack.com/services/T000/B000/xxx"


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
    notifier = SlackNotifier(WEBHOOK)
    notifier.send([])
    assert len(responses.calls) == 0


@responses.activate
def test_send_single_batch_builds_blocks_without_trailing_divider():
    responses.add(responses.POST, WEBHOOK, status=200)
    notifier = SlackNotifier(WEBHOOK)
    notifier.send([make_match("1"), make_match("2")])

    payload = json.loads(responses.calls[0].request.body)
    blocks = payload["blocks"]
    # 2 matches -> section, divider, section (no trailing divider)
    assert len(blocks) == 3
    assert blocks[0]["type"] == "section"
    assert blocks[1]["type"] == "divider"
    assert blocks[2]["type"] == "section"
    assert "GPU" in blocks[0]["text"]["text"]
    assert blocks[0]["accessory"]["image_url"] == "http://x/thumb.jpg"


@responses.activate
def test_send_splits_into_multiple_messages_over_limit():
    responses.add(responses.POST, WEBHOOK, status=200)
    responses.add(responses.POST, WEBHOOK, status=200)
    sleeps = []
    notifier = SlackNotifier(WEBHOOK, sleep=sleeps.append)

    matches = [make_match(str(i)) for i in range(30)]
    notifier.send(matches)

    assert len(responses.calls) == 2
    assert sleeps == [1.0]


@responses.activate
def test_429_retries_once_after_retry_after_header():
    responses.add(responses.POST, WEBHOOK, status=429, headers={"Retry-After": "3"})
    responses.add(responses.POST, WEBHOOK, status=200)
    sleeps = []
    notifier = SlackNotifier(WEBHOOK, sleep=sleeps.append)

    notifier.send([make_match("1")])

    assert len(responses.calls) == 2
    assert sleeps == [3.0]


def test_factory_returns_none_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert _build_from_env() is None


def test_factory_returns_notifier_when_env_var_set(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", WEBHOOK)
    notifier = _build_from_env()
    assert notifier is not None
    assert notifier.webhook_url == WEBHOOK
