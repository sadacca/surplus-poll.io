"""Persistent seen-listing store (FR11, FR12)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass

from poller.models import Listing

logger = logging.getLogger(__name__)

STATE_VERSION = 1
DEFAULT_PRUNE_AFTER_DAYS = 60


@dataclass
class SeenRecord:
    first_seen: float
    last_seen: float
    last_price: float | None
    last_bid_count: int | None
    matched_query_ids: list[str]

    def to_dict(self) -> dict:
        return {
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_price": self.last_price,
            "last_bid_count": self.last_bid_count,
            "matched_query_ids": self.matched_query_ids,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SeenRecord:
        return cls(
            first_seen=data["first_seen"],
            last_seen=data["last_seen"],
            last_price=data.get("last_price"),
            last_bid_count=data.get("last_bid_count"),
            matched_query_ids=list(data.get("matched_query_ids", [])),
        )


class SeenStore:
    """Tracks previously-seen (site, listing_id) keys across runs."""

    def __init__(self, path: str, prune_after_days: int = DEFAULT_PRUNE_AFTER_DAYS):
        self.path = path
        self.prune_after_days = prune_after_days
        self._records: dict[str, SeenRecord] = {}
        self._dirty = False
        self._load()

    @staticmethod
    def _key_to_str(key: tuple[str, str]) -> str:
        site, listing_id = key
        return f"{site}:{listing_id}"

    def _load(self) -> None:
        if not os.path.exists(self.path):
            logger.info("no existing state file at %s; starting with empty seen-store", self.path)
            return
        with open(self.path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                logger.warning("state file %s is not valid JSON; starting empty", self.path)
                return
        for key_str, record in data.get("listings", {}).items():
            self._records[key_str] = SeenRecord.from_dict(record)

    def is_new(self, listing: Listing) -> bool:
        return self._key_to_str(listing.key) not in self._records

    def get(self, listing: Listing) -> SeenRecord | None:
        return self._records.get(self._key_to_str(listing.key))

    def mark_seen(self, listing: Listing, query_id: str) -> None:
        key_str = self._key_to_str(listing.key)
        now = time.time()
        existing = self._records.get(key_str)
        if existing is None:
            self._records[key_str] = SeenRecord(
                first_seen=now,
                last_seen=now,
                last_price=listing.price,
                last_bid_count=listing.bid_count,
                matched_query_ids=[query_id],
            )
        else:
            existing.last_seen = now
            existing.last_price = listing.price
            existing.last_bid_count = listing.bid_count
            if query_id not in existing.matched_query_ids:
                existing.matched_query_ids.append(query_id)
        self._dirty = True

    def prune(self) -> int:
        cutoff = time.time() - self.prune_after_days * 86400
        stale = [k for k, r in self._records.items() if r.last_seen < cutoff]
        for k in stale:
            del self._records[k]
        if stale:
            self._dirty = True
        return len(stale)

    def save(self) -> None:
        if not self._dirty:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        payload = {
            "version": STATE_VERSION,
            "listings": {k: v.to_dict() for k, v in self._records.items()},
        }
        dir_ = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".seen-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        self._dirty = False
