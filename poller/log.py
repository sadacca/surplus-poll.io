"""Logging setup and end-of-run summary (FR17)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

RUNTIME_WARN_THRESHOLD_SECONDS = 90


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@dataclass
class RunSummary:
    """Accumulates per-run stats for the FR17 end-of-run summary line."""

    queries_executed: int = 0
    listings_found: int = 0
    new_matches: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float | None = None

    def add_error(self, site: str, query_id: str, message: str) -> None:
        self.errors.append(f"{site}/{query_id}: {message}")

    def log(self, logger: logging.Logger) -> None:
        logger.info(
            "run summary: queries=%d listings_found=%d new_matches=%d errors=%d duration=%s",
            self.queries_executed,
            self.listings_found,
            self.new_matches,
            len(self.errors),
            f"{self.duration_seconds:.1f}s" if self.duration_seconds is not None else "n/a",
        )
        for err in self.errors:
            logger.warning("  error: %s", err)
        over_budget = (
            self.duration_seconds is not None
            and self.duration_seconds > RUNTIME_WARN_THRESHOLD_SECONDS
        )
        if over_budget:
            logger.warning(
                "run took %.1fs, over the %ds budget guideline (FR9) — "
                "consider raising the per-site rate limit delay, lowering the page cap, "
                "or splitting queries across more frequent smaller runs",
                self.duration_seconds,
                RUNTIME_WARN_THRESHOLD_SECONDS,
            )
