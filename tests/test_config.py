import os

import pytest

from poller.config import ConfigError, load_and_validate, load_queries, validate_queries

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "queries")
KNOWN_SITES = {"publicsurplus", "govdeals"}
KNOWN_CHANNELS = {"discord", "slack"}


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def test_load_queries_parses_fr1_example():
    queries = load_queries(fixture("valid.yaml"))
    assert len(queries) == 2

    gpu = queries[0]
    assert gpu.id == "gpu-search"
    assert gpu.label == "Server GPUs"
    assert gpu.enabled is True
    assert gpu.sites == ("publicsurplus", "govdeals")
    assert gpu.keywords == ("nvidia", "gpu", "tesla")
    assert gpu.exclude_keywords == ("case", "sleeve")
    assert gpu.category == "Computer Equipment"
    assert gpu.max_price == 500
    assert gpu.state == "CA"
    assert gpu.zip == "94103"
    assert gpu.radius_miles == 200
    assert gpu.notify == ("discord",)

    switches = queries[1]
    assert switches.enabled is False
    assert switches.notify == ("discord", "slack")


def test_valid_file_has_no_errors():
    queries = load_queries(fixture("valid.yaml"))
    errors = validate_queries(queries, known_sites=KNOWN_SITES, known_channels=KNOWN_CHANNELS)
    assert errors == []


def test_load_and_validate_returns_queries_for_valid_file():
    queries = load_and_validate(
        fixture("valid.yaml"), known_sites=KNOWN_SITES, known_channels=KNOWN_CHANNELS
    )
    assert len(queries) == 2


@pytest.mark.parametrize(
    "filename,expected_substring",
    [
        ("missing_fields.yaml", "missing required field 'id'"),
        ("missing_fields.yaml", "missing required field 'label'"),
        ("missing_fields.yaml", "missing required field 'sites'"),
        ("missing_fields.yaml", "missing required field 'keywords'"),
        ("bad_enabled.yaml", "'enabled' must be a boolean"),
        ("unknown_site.yaml", "unknown site 'ebay'"),
        ("duplicate_id.yaml", "duplicate query id 'dup'"),
        ("negative_price.yaml", "'max_price' must not be negative"),
        ("unknown_channel.yaml", "unknown notify channel 'pagerduty'"),
    ],
)
def test_invalid_files_report_clear_errors(filename, expected_substring):
    queries = load_queries(fixture(filename))
    errors = validate_queries(queries, known_sites=KNOWN_SITES, known_channels=KNOWN_CHANNELS)
    assert any(expected_substring in e for e in errors), errors


def test_load_and_validate_raises_config_error_for_invalid_file():
    with pytest.raises(ConfigError) as exc_info:
        load_and_validate(
            fixture("unknown_site.yaml"), known_sites=KNOWN_SITES, known_channels=KNOWN_CHANNELS
        )
    assert "unknown_site.yaml" in str(exc_info.value)
    assert "unknown site 'ebay'" in str(exc_info.value)


def test_disabled_query_still_loads():
    queries = load_queries(fixture("valid.yaml"))
    disabled = [q for q in queries if not q.enabled]
    assert len(disabled) == 1
    assert disabled[0].id == "rack-switches"
