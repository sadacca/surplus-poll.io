import argparse
import logging

import pytest

import poller.__main__ as main_module
from poller.adapters import ADAPTERS
from poller.health import ALERT_THRESHOLD, HealthTracker
from poller.models import Listing, Match
from poller.notify import NOTIFIER_FACTORIES
from poller.state import SeenStore
from tests.fakes import FakeAdapter


class FakeNotifier:
    name = "fake"

    def __init__(self, should_fail: bool = False):
        self.sent_batches: list[list[Match]] = []
        self.should_fail = should_fail

    def send(self, matches):
        from poller.notify.base import NotifyError

        if self.should_fail:
            raise NotifyError("boom")
        self.sent_batches.append(list(matches))

    def send_text(self, text: str) -> None:
        self.texts = getattr(self, "texts", [])
        self.texts.append(text)


@pytest.fixture(autouse=True)
def clean_registries():
    ADAPTERS.clear()
    NOTIFIER_FACTORIES.clear()
    yield
    ADAPTERS.clear()
    NOTIFIER_FACTORIES.clear()


def write_config(tmp_path, text: str) -> str:
    path = tmp_path / "queries.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def make_args(tmp_path, **overrides):
    defaults = dict(
        config=None,
        state=str(tmp_path / "seen.json"),
        health=str(tmp_path / "health.json"),
        dry_run=False,
        query_id=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


VALID_CONFIG = """
queries:
  - id: gpu-search
    label: "Server GPUs"
    enabled: true
    sites: [fake-site]
    keywords: ["gpu"]
    notify: [fake]
"""


def test_run_notifies_new_listing_and_marks_seen(tmp_path, monkeypatch):
    listing = Listing(site="fake-site", listing_id="1", title="GPU", url="http://x", price=100.0)
    fake_adapter = FakeAdapter("fake-site", listings=[listing])
    fake_notifier = FakeNotifier()
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["fake"] = lambda: fake_notifier
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config_path = write_config(tmp_path, VALID_CONFIG)
    args = make_args(tmp_path, config=config_path)

    exit_code = main_module.cmd_run(args)

    assert exit_code == main_module.EXIT_OK
    assert len(fake_notifier.sent_batches) == 1
    assert fake_notifier.sent_batches[0][0].listing.listing_id == "1"

    store = SeenStore(args.state)
    assert not store.is_new(listing)


def test_run_does_not_renotify_seen_listing(tmp_path, monkeypatch):
    listing = Listing(site="fake-site", listing_id="1", title="GPU", url="http://x", price=100.0)
    fake_adapter = FakeAdapter("fake-site", listings=[listing])
    fake_notifier = FakeNotifier()
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["fake"] = lambda: fake_notifier
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config_path = write_config(tmp_path, VALID_CONFIG)
    args = make_args(tmp_path, config=config_path)

    main_module.cmd_run(args)
    main_module.cmd_run(args)

    assert len(fake_notifier.sent_batches) == 1  # second run found nothing new


def test_run_continues_after_adapter_error(tmp_path, monkeypatch, caplog):
    fake_adapter = FakeAdapter("fake-site", error="site is down")
    fake_notifier = FakeNotifier()
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["fake"] = lambda: fake_notifier
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config_path = write_config(tmp_path, VALID_CONFIG)
    args = make_args(tmp_path, config=config_path)

    with caplog.at_level(logging.WARNING):
        exit_code = main_module.cmd_run(args)

    assert exit_code == main_module.EXIT_OK  # FR18: a site failure does not abort the run
    assert "site is down" in caplog.text
    assert fake_notifier.sent_batches == []


def test_failed_notification_does_not_mark_listing_seen(tmp_path, monkeypatch):
    listing = Listing(site="fake-site", listing_id="1", title="GPU", url="http://x", price=100.0)
    fake_adapter = FakeAdapter("fake-site", listings=[listing])
    fake_notifier = FakeNotifier(should_fail=True)
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["fake"] = lambda: fake_notifier
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config_path = write_config(tmp_path, VALID_CONFIG)
    args = make_args(tmp_path, config=config_path)

    main_module.cmd_run(args)

    store = SeenStore(args.state)
    assert store.is_new(listing)  # not marked seen; will retry next run


def test_dry_run_does_not_notify_or_write_state(tmp_path, monkeypatch):
    listing = Listing(site="fake-site", listing_id="1", title="GPU", url="http://x", price=100.0)
    fake_adapter = FakeAdapter("fake-site", listings=[listing])
    fake_notifier = FakeNotifier()
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["fake"] = lambda: fake_notifier
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config_path = write_config(tmp_path, VALID_CONFIG)
    args = make_args(tmp_path, config=config_path, dry_run=True)

    main_module.cmd_run(args)

    assert fake_notifier.sent_batches == []
    import os

    assert not os.path.exists(args.state)


def test_disabled_query_is_skipped(tmp_path, monkeypatch):
    config = """
queries:
  - id: gpu-search
    label: "Server GPUs"
    enabled: false
    sites: [fake-site]
    keywords: ["gpu"]
    notify: [fake]
"""
    fake_adapter = FakeAdapter("fake-site")
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["fake"] = lambda: FakeNotifier()
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config_path = write_config(tmp_path, config)
    args = make_args(tmp_path, config=config_path)

    main_module.cmd_run(args)

    assert fake_adapter.calls == []


def test_query_id_forces_disabled_query_to_run(tmp_path, monkeypatch):
    config = """
queries:
  - id: gpu-search
    label: "Server GPUs"
    enabled: false
    sites: [fake-site]
    keywords: ["gpu"]
    notify: [fake]
"""
    fake_adapter = FakeAdapter("fake-site")
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["fake"] = lambda: FakeNotifier()
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config_path = write_config(tmp_path, config)
    args = make_args(tmp_path, config=config_path, query_id="gpu-search")

    main_module.cmd_run(args)

    assert len(fake_adapter.calls) == 1


def test_invalid_config_returns_config_error_exit_code(tmp_path, monkeypatch):
    ADAPTERS["fake-site"] = FakeAdapter("fake-site")
    NOTIFIER_FACTORIES["fake"] = lambda: FakeNotifier()
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    invalid_config = "queries:\n  - label: 'no id'\n    sites: [fake-site]\n    keywords: ['gpu']\n"
    config_path = write_config(tmp_path, invalid_config)
    args = make_args(tmp_path, config=config_path)

    exit_code = main_module.cmd_run(args)
    assert exit_code == main_module.EXIT_CONFIG_ERROR


def test_third_consecutive_failure_sends_alert(tmp_path, monkeypatch):
    fake_adapter = FakeAdapter("fake-site", error="boom")
    fake_notifier = FakeNotifier()
    ADAPTERS["fake-site"] = fake_adapter
    NOTIFIER_FACTORIES["discord"] = lambda: fake_notifier
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config = """
queries:
  - id: gpu-search
    label: "Server GPUs"
    enabled: true
    sites: [fake-site]
    keywords: ["gpu"]
    notify: []
"""
    config_path = write_config(tmp_path, config)
    args = make_args(tmp_path, config=config_path)

    for _ in range(ALERT_THRESHOLD - 1):
        main_module.cmd_run(args)
    assert getattr(fake_notifier, "texts", []) == []

    main_module.cmd_run(args)
    assert len(fake_notifier.texts) == 1
    assert "may be broken" in fake_notifier.texts[0]

    # a fourth failure must not re-alert
    main_module.cmd_run(args)
    assert len(fake_notifier.texts) == 1


def test_recovery_alert_sent_after_broken_streak(tmp_path, monkeypatch):
    fake_notifier = FakeNotifier()
    NOTIFIER_FACTORIES["discord"] = lambda: fake_notifier
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config = """
queries:
  - id: gpu-search
    label: "Server GPUs"
    enabled: true
    sites: [fake-site]
    keywords: ["gpu"]
    notify: []
"""
    config_path = write_config(tmp_path, config)
    args = make_args(tmp_path, config=config_path)

    ADAPTERS["fake-site"] = FakeAdapter("fake-site", error="boom")
    for _ in range(ALERT_THRESHOLD):
        main_module.cmd_run(args)
    assert len(fake_notifier.texts) == 1

    ADAPTERS["fake-site"] = FakeAdapter("fake-site", listings=[])
    main_module.cmd_run(args)
    assert len(fake_notifier.texts) == 2
    assert "recovered" in fake_notifier.texts[1]


def test_health_state_persists_across_runs(tmp_path, monkeypatch):
    NOTIFIER_FACTORIES["discord"] = lambda: FakeNotifier()
    monkeypatch.setattr(main_module, "bootstrap", lambda: {})

    config = """
queries:
  - id: gpu-search
    label: "Server GPUs"
    enabled: true
    sites: [fake-site]
    keywords: ["gpu"]
    notify: []
"""
    config_path = write_config(tmp_path, config)
    args = make_args(tmp_path, config=config_path)
    health_path = args.health

    ADAPTERS["fake-site"] = FakeAdapter("fake-site", error="boom")
    main_module.cmd_run(args)
    main_module.cmd_run(args)

    tracker = HealthTracker(health_path)
    assert tracker.record_failure("fake-site") is True  # third failure alerts
