from poller.health import ALERT_THRESHOLD, HealthTracker


def test_first_two_failures_do_not_alert(tmp_path):
    tracker = HealthTracker(str(tmp_path / "health.json"))
    assert tracker.record_failure("publicsurplus") is False
    assert tracker.record_failure("publicsurplus") is False


def test_third_consecutive_failure_alerts_once(tmp_path):
    tracker = HealthTracker(str(tmp_path / "health.json"))
    for _ in range(ALERT_THRESHOLD - 1):
        tracker.record_failure("publicsurplus")
    assert tracker.record_failure("publicsurplus") is True
    # a fourth failure must not re-alert
    assert tracker.record_failure("publicsurplus") is False


def test_success_resets_failure_count(tmp_path):
    tracker = HealthTracker(str(tmp_path / "health.json"))
    tracker.record_failure("publicsurplus")
    tracker.record_failure("publicsurplus")
    tracker.record_success("publicsurplus")
    for _ in range(ALERT_THRESHOLD - 1):
        assert tracker.record_failure("publicsurplus") is False
    assert tracker.record_failure("publicsurplus") is True


def test_success_after_alert_reports_recovery(tmp_path):
    tracker = HealthTracker(str(tmp_path / "health.json"))
    for _ in range(ALERT_THRESHOLD):
        tracker.record_failure("publicsurplus")
    assert tracker.record_success("publicsurplus") is True
    # a second success in a row must not re-report recovery
    assert tracker.record_success("publicsurplus") is False


def test_success_on_healthy_site_is_not_a_recovery(tmp_path):
    tracker = HealthTracker(str(tmp_path / "health.json"))
    assert tracker.record_success("publicsurplus") is False


def test_round_trip_persists_alert_state(tmp_path):
    path = str(tmp_path / "health.json")
    tracker = HealthTracker(path)
    for _ in range(ALERT_THRESHOLD):
        tracker.record_failure("publicsurplus")
    tracker.save()

    reloaded = HealthTracker(path)
    # already alerted, so a 4th failure must still not double-alert
    assert reloaded.record_failure("publicsurplus") is False


def test_save_is_noop_when_not_dirty(tmp_path):
    path = tmp_path / "health.json"
    tracker = HealthTracker(str(path))
    tracker.save()
    assert not path.exists()


def test_sites_tracked_independently(tmp_path):
    tracker = HealthTracker(str(tmp_path / "health.json"))
    for _ in range(ALERT_THRESHOLD):
        tracker.record_failure("publicsurplus")
    assert tracker.record_failure("govdeals") is False
