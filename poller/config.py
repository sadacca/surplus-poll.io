"""Load and validate queries.yaml (FR1, FR3, FR4)."""

from __future__ import annotations

import logging

import yaml

from poller.adapters import ADAPTERS
from poller.models import Query
from poller.notify import NOTIFIER_FACTORIES

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "label", "sites", "keywords")


class ConfigError(Exception):
    """Raised when queries.yaml fails schema validation (FR3)."""


def _as_tuple(value) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def load_queries(path: str) -> list[Query]:
    """Parse queries.yaml into a list of Query objects. Does not validate."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw_queries = data.get("queries", [])
    queries: list[Query] = []
    for raw in raw_queries:
        queries.append(
            Query(
                id=raw.get("id"),
                label=raw.get("label", ""),
                enabled=raw.get("enabled", True),
                sites=_as_tuple(raw.get("sites")),
                keywords=_as_tuple(raw.get("keywords")),
                exclude_keywords=_as_tuple(raw.get("exclude_keywords")),
                category=raw.get("category"),
                max_price=raw.get("max_price"),
                state=raw.get("state"),
                zip=raw.get("zip"),
                radius_miles=raw.get("radius_miles"),
                notify=_as_tuple(raw.get("notify")),
            )
        )
    return queries


def validate_queries(
    queries: list[Query],
    known_sites: set[str] | None = None,
    known_channels: set[str] | None = None,
) -> list[str]:
    """Return a list of human-readable error strings; empty means valid.

    known_sites/known_channels default to the live adapter/notifier registries
    so `python -m poller validate` checks against what's actually registered.
    """
    if known_sites is None:
        known_sites = set(ADAPTERS.keys())
    if known_channels is None:
        known_channels = set(NOTIFIER_FACTORIES.keys())

    errors: list[str] = []
    seen_ids: set[str] = set()

    for i, q in enumerate(queries):
        ref = q.id or f"<query at index {i}>"

        if not q.id:
            errors.append(f"{ref}: missing required field 'id'")
        elif q.id in seen_ids:
            errors.append(f"{ref}: duplicate query id '{q.id}'")
        else:
            seen_ids.add(q.id)

        if not q.label:
            errors.append(f"{ref}: missing required field 'label'")

        if not isinstance(q.enabled, bool):
            errors.append(f"{ref}: 'enabled' must be a boolean, got {q.enabled!r}")

        if not q.sites:
            errors.append(f"{ref}: missing required field 'sites'")
        else:
            for site in q.sites:
                if site not in known_sites:
                    errors.append(
                        f"{ref}: unknown site '{site}' (known sites: {sorted(known_sites)})"
                    )

        if not q.keywords:
            errors.append(f"{ref}: missing required field 'keywords'")

        if q.max_price is not None and q.max_price < 0:
            errors.append(f"{ref}: 'max_price' must not be negative, got {q.max_price!r}")

        for channel in q.notify:
            if channel not in known_channels:
                errors.append(
                    f"{ref}: unknown notify channel '{channel}' "
                    f"(known channels: {sorted(known_channels)})"
                )

    return errors


def load_and_validate(
    path: str,
    known_sites: set[str] | None = None,
    known_channels: set[str] | None = None,
) -> list[Query]:
    """Load queries.yaml and raise ConfigError with all problems if invalid."""
    queries = load_queries(path)
    errors = validate_queries(queries, known_sites=known_sites, known_channels=known_channels)
    if errors:
        raise ConfigError(
            f"{path} failed validation ({len(errors)} problem(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
    return queries
