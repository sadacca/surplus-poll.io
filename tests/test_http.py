import pytest
import requests
import responses

from poller.adapters.base import SiteError
from poller.http import RateLimitedClient


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_client(min_delay=2.5):
    clock = FakeClock()
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    client = RateLimitedClient(
        min_delay_seconds=min_delay,
        session=requests.Session(),
        sleep=fake_sleep,
        clock=clock,
    )
    return client, sleeps, clock


@responses.activate
def test_second_request_to_same_site_is_delayed():
    responses.add(responses.GET, "http://x/a", status=200)
    responses.add(responses.GET, "http://x/b", status=200)
    client, sleeps, clock = make_client(min_delay=2.5)

    client.get("publicsurplus", "http://x/a")
    clock.advance(1.0)  # only 1s elapsed, less than the 2.5s minimum
    client.get("publicsurplus", "http://x/b")

    assert sleeps == [1.5]


@responses.activate
def test_no_delay_when_enough_time_has_passed():
    responses.add(responses.GET, "http://x/a", status=200)
    responses.add(responses.GET, "http://x/b", status=200)
    client, sleeps, clock = make_client(min_delay=2.5)

    client.get("publicsurplus", "http://x/a")
    clock.advance(5.0)
    client.get("publicsurplus", "http://x/b")

    assert sleeps == []


@responses.activate
def test_different_sites_do_not_share_rate_limit():
    responses.add(responses.GET, "http://x/a", status=200)
    responses.add(responses.GET, "http://y/b", status=200)
    client, sleeps, clock = make_client(min_delay=2.5)

    client.get("publicsurplus", "http://x/a")
    client.get("govdeals", "http://y/b")

    assert sleeps == []


@responses.activate
def test_non_200_raises_site_error():
    responses.add(responses.GET, "http://x/a", status=404)
    client, _, _ = make_client()

    with pytest.raises(SiteError, match="404"):
        client.get("publicsurplus", "http://x/a")


@responses.activate
def test_5xx_is_retried_once_then_succeeds():
    responses.add(responses.GET, "http://x/a", status=503)
    responses.add(responses.GET, "http://x/a", status=200)
    client, _, _ = make_client()

    response = client.get("publicsurplus", "http://x/a")
    assert response.status_code == 200
    assert len(responses.calls) == 2


@responses.activate
def test_5xx_twice_raises_site_error():
    responses.add(responses.GET, "http://x/a", status=503)
    responses.add(responses.GET, "http://x/a", status=503)
    client, _, _ = make_client()

    with pytest.raises(SiteError, match="503"):
        client.get("publicsurplus", "http://x/a")


@responses.activate
def test_timeout_is_retried_once_then_raises():
    responses.add(
        responses.GET,
        "http://x/a",
        body=requests.exceptions.ConnectTimeout("boom"),
    )
    responses.add(
        responses.GET,
        "http://x/a",
        body=requests.exceptions.ConnectTimeout("boom"),
    )
    client, _, _ = make_client()

    with pytest.raises(SiteError, match="publicsurplus"):
        client.get("publicsurplus", "http://x/a")


def test_user_agent_header_is_set():
    client, _, _ = make_client()
    assert "surplus-poller" in client.session.headers["User-Agent"]
