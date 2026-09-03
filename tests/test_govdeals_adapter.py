import os

import responses

from poller.adapters.govdeals import GovDealsAdapter, build_search_url, parse_results
from poller.http import RateLimitedClient
from poller.models import Query

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "govdeals")


def read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def make_query(**overrides) -> Query:
    defaults = dict(
        id="gpu-search",
        label="Server GPUs",
        enabled=True,
        sites=("govdeals",),
        keywords=("nvidia", "gpu"),
        exclude_keywords=(),
        max_price=None,
        category=None,
        state=None,
    )
    defaults.update(overrides)
    return Query(**defaults)


def test_build_search_url_includes_keywords_and_page():
    url = build_search_url(make_query(), page=2)
    assert "keywords=nvidia+gpu" in url
    assert "page=2" in url


def test_parse_results_extracts_all_fields():
    html = read_fixture("search_results.html")
    listings = parse_results(html)
    assert len(listings) == 3

    first = listings[0]
    assert first.site == "govdeals"
    assert first.listing_id == "2001"
    assert first.title == "NVIDIA GPU Server Rack"
    assert first.url == "https://www.govdeals.com/item/2001"
    assert first.price == 250.00
    assert first.bid_count == 5
    assert first.end_time == "2d 4h left"
    assert first.thumbnail_url == "https://cdn.govdeals.com/2001/thumb.jpg"


def test_parse_results_empty_page_returns_empty_list():
    assert parse_results(read_fixture("no_results.html")) == []


@responses.activate
def test_search_applies_exclude_keywords_and_max_price():
    query = make_query(exclude_keywords=("sleeve",), max_price=1000)
    for page in (1, 2, 3):
        url = build_search_url(query, page)
        body = read_fixture("search_results.html") if page == 1 else read_fixture("no_results.html")
        responses.add(responses.GET, url, body=body, status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = GovDealsAdapter(client)
    listings = adapter.search(query)

    ids = {listing.listing_id for listing in listings}
    assert ids == {"2001"}  # 2002 excluded by keyword, 2003 excluded by max_price


@responses.activate
def test_search_stops_pagination_when_a_page_is_empty():
    query = make_query()
    page1_url = build_search_url(query, 1)
    responses.add(responses.GET, page1_url, body=read_fixture("no_results.html"), status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = GovDealsAdapter(client)
    listings = adapter.search(query)

    assert listings == []
    assert len(responses.calls) == 1
