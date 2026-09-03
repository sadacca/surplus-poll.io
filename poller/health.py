"""Per-site run-health tracking (FR18, FR19)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ALERT_THRESHOLD = 3


@dataclass
class SiteHealth:
    consecutive_failures: int = 0
    alerted: bool = False

    def to_dict(self) -> dict:
        return {"consecutive_failures": self.consecutive_failures, "alerted": self.alerted}

    @classmethod
    def from_dict(cls, data: dict) -> SiteHealth:
        return cls(
            consecutive_failures=data.get("consecutive_failures", 0),
            alerted=data.get("alerted", False),
        )


class HealthTracker:
    """Tracks consecutive per-site failures across runs (FR19).

    record_failure returns True exactly once per outage, on the run where the
    failure count first reaches ALERT_THRESHOLD, so the caller sends a single
    "adapter may be broken" notification. record_success returns True when a
    previously-alerted site recovers, so the caller can send one "recovered"
    notification.
    """

    def __init__(self, path: str):
        self.path = path
        self._sites: dict[str, SiteHealth] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                logger.warning("health file %s is not valid JSON; starting empty", self.path)
                return
        for site, record in data.get("sites", {}).items():
            self._sites[site] = SiteHealth.from_dict(record)

    def record_failure(self, site: str) -> bool:
        health = self._sites.setdefault(site, SiteHealth())
        health.consecutive_failures += 1
        self._dirty = True
        should_alert = health.consecutive_failures >= ALERT_THRESHOLD and not health.alerted
        if should_alert:
            health.alerted = True
        return should_alert

    def record_success(self, site: str) -> bool:
        health = self._sites.get(site)
        if health is None:
            return False
        was_alerted = health.alerted
        if health.consecutive_failures > 0 or health.alerted:
            self._dirty = True
        health.consecutive_failures = 0
        health.alerted = False
        return was_alerted

    def save(self) -> None:
        if not self._dirty:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        payload = {"sites": {site: h.to_dict() for site, h in self._sites.items()}}
        dir_ = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".health-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        self._dirty = False
