from poller.models import Listing, Match, Query
from poller.notify import NOTIFIER_FACTORIES, build_notifiers, register


class FakeNotifier:
    name = "fake"

    def __init__(self):
        self.sent: list[Match] = []

    def send(self, matches):
        self.sent.extend(matches)


def test_build_notifiers_skips_unknown_channel(caplog):
    NOTIFIER_FACTORIES.clear()
    notifiers = build_notifiers({"nonexistent"})
    assert notifiers == {}
    assert "unknown notification channel" in caplog.text


def test_build_notifiers_skips_unconfigured_channel(caplog):
    NOTIFIER_FACTORIES.clear()
    register("fake", lambda: None)
    notifiers = build_notifiers({"fake"})
    assert notifiers == {}
    assert "no webhook configured" in caplog.text


def test_build_notifiers_returns_configured_channel():
    NOTIFIER_FACTORIES.clear()
    fake = FakeNotifier()
    register("fake", lambda: fake)
    notifiers = build_notifiers({"fake"})
    assert notifiers == {"fake": fake}


def test_fake_notifier_receives_matches():
    fake = FakeNotifier()
    q = Query(id="q1", label="Q1", enabled=True, sites=("publicsurplus",), keywords=("gpu",))
    listing = Listing(site="publicsurplus", listing_id="1", title="GPU", url="http://x")
    fake.send([Match(listing=listing, query=q)])
    assert len(fake.sent) == 1
