
from poller.config import load_queries, validate_queries
from scripts.issue_to_query import (
    append_query_to_file,
    build_query_from_issue,
    parse_checked_options,
    parse_sections,
    slugify,
    unique_id,
)

SAMPLE_BODY = """### Label

Server GPUs

### Keywords

nvidia, gpu, tesla

### Exclude keywords

case, sleeve

### Sites

- [X] PublicSurplus
- [ ] GovDeals

### Max price (USD)

500

### State

CA

### ZIP code

_No response_

### Radius (miles)

_No response_

### Notify

- [X] Discord
- [ ] Slack
"""


def test_parse_sections_splits_on_headers():
    sections = parse_sections(SAMPLE_BODY)
    assert sections["Label"] == "Server GPUs"
    assert sections["Keywords"] == "nvidia, gpu, tesla"
    assert sections["ZIP code"] == "_No response_"


def test_parse_checked_options_only_returns_checked():
    checked = parse_checked_options(parse_sections(SAMPLE_BODY)["Sites"])
    assert checked == ["PublicSurplus"]


def test_slugify():
    assert slugify("Server GPUs") == "server-gpus"
    assert slugify("10G Switches!") == "10g-switches"


def test_unique_id_disambiguates_collision():
    assert unique_id("gpu-search", set()) == "gpu-search"
    assert unique_id("gpu-search", {"gpu-search"}) == "gpu-search-2"
    assert unique_id("gpu-search", {"gpu-search", "gpu-search-2"}) == "gpu-search-3"


def test_build_query_from_issue_maps_all_fields():
    query = build_query_from_issue(SAMPLE_BODY, existing_ids=set())
    assert query.id == "server-gpus"
    assert query.label == "Server GPUs"
    assert query.enabled is True
    assert query.sites == ("publicsurplus",)
    assert query.keywords == ("nvidia", "gpu", "tesla")
    assert query.exclude_keywords == ("case", "sleeve")
    assert query.max_price == 500.0
    assert query.state == "CA"
    assert query.zip is None
    assert query.radius_miles is None
    assert query.notify == ("discord",)


def test_build_query_from_issue_disambiguates_against_existing_ids():
    query = build_query_from_issue(SAMPLE_BODY, existing_ids={"server-gpus"})
    assert query.id == "server-gpus-2"


def test_new_query_passes_validation():
    query = build_query_from_issue(SAMPLE_BODY, existing_ids=set())
    errors = validate_queries(
        [query], known_sites={"publicsurplus", "govdeals"}, known_channels={"discord", "slack"}
    )
    assert errors == []


def test_append_query_to_file_preserves_existing_content_and_is_valid(tmp_path):
    path = tmp_path / "queries.yaml"
    path.write_text(
        "# a header comment\nqueries:\n  - id: existing\n    label: Existing\n"
        "    enabled: true\n    sites: [publicsurplus]\n    keywords: [gpu]\n",
        encoding="utf-8",
    )

    query = build_query_from_issue(SAMPLE_BODY, existing_ids={"existing"})
    append_query_to_file(str(path), query)

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# a header comment\n")
    assert "id: existing" in text
    assert f"id: {query.id}" in text

    queries = load_queries(str(path))
    ids = {q.id for q in queries}
    assert ids == {"existing", query.id}


def test_missing_required_field_fails_validation():
    body = SAMPLE_BODY.replace(
        "### Keywords\n\nnvidia, gpu, tesla\n\n", "### Keywords\n\n_No response_\n\n"
    )
    query = build_query_from_issue(body, existing_ids=set())
    errors = validate_queries(
        [query], known_sites={"publicsurplus", "govdeals"}, known_channels={"discord", "slack"}
    )
    assert any("keywords" in e for e in errors)
