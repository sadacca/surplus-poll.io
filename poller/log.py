"""Logging setup and end-of-run summary (FR17)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field


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

    def add_error(self, site: str, query_id: str, message: str) -> None:
        self.errors.append(f"{site}/{query_id}: {message}")

    def log(self, logger: logging.Logger) -> None:
        logger.info(
            "run summary: queries=%d listings_found=%d new_matches=%d errors=%d",
            self.queries_executed,
            self.listings_found,
            self.new_matches,
            len(self.errors),
        )
        for err in self.errors:
            logger.warning("  error: %s", err)
