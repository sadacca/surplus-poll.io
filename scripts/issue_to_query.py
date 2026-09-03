"""Parse a `new-query` Issue Form submission into a queries.yaml entry (FR2).

Invoked by .github/workflows/add-query.yml with the issue body on stdin and
the target queries.yaml path as argv[1]. Prints either:
  QUERY_ID=<id>            (success; the entry was appended)
or:
  ERROR=<message>          (validation failed; nothing was written)
so the workflow can branch on it without parsing structured output.
"""

from __future__ import annotations

import re
import sys

import yaml

from poller.config import load_queries, validate_queries
from poller.models import Query

_HEADER_RE = re.compile(r"^### (.+?)\s*$", re.MULTILINE)
_CHECKED_RE = re.compile(r"^- \[[xX]\]\s*(.+?)\s*$", re.MULTILINE)

_SITE_LABELS = {"publicsurplus": "publicsurplus", "govdeals": "govdeals"}
_CHANNEL_LABELS = {"discord": "discord", "slack": "slack"}

_FIELD_HEADERS = {
    "Label": "label",
    "Keywords": "keywords",
    "Exclude keywords": "exclude_keywords",
    "Sites": "sites",
    "Max price (USD)": "max_price",
    "State": "state",
    "ZIP code": "zip",
    "Radius (miles)": "radius_miles",
    "Notify": "notify",
}


def parse_sections(body: str) -> dict[str, str]:
    """Split a GitHub Issue Form body into {header text: raw content}."""
    headers = list(_HEADER_RE.finditer(body))
    sections: dict[str, str] = {}
    for i, match in enumerate(headers):
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        sections[match.group(1)] = body[start:end].strip()
    return sections


def parse_checked_options(content: str) -> list[str]:
    return [m.group(1).strip() for m in _CHECKED_RE.finditer(content)]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value == "_No response_":
        return None
    return value


def _split_csv(value: str | None) -> list[str]:
    cleaned = _clean(value)
    if not cleaned:
        return []
    return [part.strip() for part in cleaned.split(",") if part.strip()]


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "query"


def unique_id(base_slug: str, existing_ids: set[str]) -> str:
    if base_slug not in existing_ids:
        return base_slug
    n = 2
    while f"{base_slug}-{n}" in existing_ids:
        n += 1
    return f"{base_slug}-{n}"


def build_query_from_issue(body: str, existing_ids: set[str]) -> Query:
    sections = parse_sections(body)
    fields = {_FIELD_HEADERS[h]: v for h, v in sections.items() if h in _FIELD_HEADERS}

    label = _clean(fields.get("label")) or ""
    query_id = unique_id(slugify(label), existing_ids)

    sites = tuple(
        _SITE_LABELS[opt.lower()]
        for opt in parse_checked_options(fields.get("sites", ""))
        if opt.lower() in _SITE_LABELS
    )
    notify = tuple(
        _CHANNEL_LABELS[opt.lower()]
        for opt in parse_checked_options(fields.get("notify", ""))
        if opt.lower() in _CHANNEL_LABELS
    )

    max_price_raw = _clean(fields.get("max_price"))
    radius_raw = _clean(fields.get("radius_miles"))

    return Query(
        id=query_id,
        label=label,
        enabled=True,
        sites=sites,
        keywords=tuple(_split_csv(fields.get("keywords"))),
        exclude_keywords=tuple(_split_csv(fields.get("exclude_keywords"))),
        category=None,
        max_price=float(max_price_raw) if max_price_raw else None,
        state=_clean(fields.get("state")),
        zip=_clean(fields.get("zip")),
        radius_miles=float(radius_raw) if radius_raw else None,
        notify=notify,
    )


def query_to_yaml_dict(query: Query) -> dict:
    d = {
        "id": query.id,
        "label": query.label,
        "enabled": query.enabled,
        "sites": list(query.sites),
        "keywords": list(query.keywords),
    }
    if query.exclude_keywords:
        d["exclude_keywords"] = list(query.exclude_keywords)
    if query.category:
        d["category"] = query.category
    if query.max_price is not None:
        d["max_price"] = query.max_price
    if query.state:
        d["state"] = query.state
    if query.zip:
        d["zip"] = query.zip
    if query.radius_miles is not None:
        d["radius_miles"] = query.radius_miles
    if query.notify:
        d["notify"] = list(query.notify)
    return d


def append_query_to_file(config_path: str, query: Query) -> None:
    """Append `query` to the `queries:` list, preserving the rest of the
    file's text (so comments/formatting survive)."""
    with open(config_path, encoding="utf-8") as f:
        original_text = f.read()

    block = yaml.safe_dump(
        [query_to_yaml_dict(query)], sort_keys=False, default_flow_style=False, indent=2
    )
    # Re-indent the single-item list as an appended entry under `queries:`.
    indented = "\n".join("  " + line if line else line for line in block.splitlines())

    new_text = original_text.rstrip("\n") + "\n" + indented + "\n"
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_text)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("ERROR=usage: issue_to_query.py <queries.yaml path> (body on stdin)")
        return 1
    config_path = argv[1]
    body = sys.stdin.read()

    existing_queries = load_queries(config_path)
    existing_ids = {q.id for q in existing_queries}

    try:
        new_query = build_query_from_issue(body, existing_ids)
    except Exception as exc:  # noqa: BLE001 - report any parse failure to the issue
        print(f"ERROR=could not parse the issue form: {exc}")
        return 1

    errors = validate_queries(
        [new_query],
        known_sites=set(_SITE_LABELS.values()),
        known_channels=set(_CHANNEL_LABELS.values()),
    )
    if errors:
        print("ERROR=" + "; ".join(errors))
        return 1

    append_query_to_file(config_path, new_query)
    print(f"QUERY_ID={new_query.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
