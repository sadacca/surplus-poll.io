import os

import responses

from poller.adapters.publicsurplus import PublicSurplusAdapter, build_search_url, parse_results
from poller.http import RateLimitedClient
from poller.models import Query

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "publicsurplus")


def read_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def make_query(**overrides) -> Query:
    defaults = dict(
        id="gpu-search",
        label="Server GPUs",
        enabled=True,
        sites=("publicsurplus",),
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
    assert "searchtext=nvidia+gpu" in url
    assert "page=2" in url


def test_build_search_url_includes_optional_filters():
    url = build_search_url(make_query(category="Computer Equipment", state="CA"), page=1)
    assert "category=Computer+Equipment" in url
    assert "state=CA" in url


def test_parse_results_extracts_all_fields():
    html = read_fixture("search_results.html")
    listings = parse_results(html)
    assert len(listings) == 3

    first = listings[0]
    assert first.site == "publicsurplus"
    assert first.listing_id == "1001"
    assert first.title == "NVIDIA Tesla V100 GPU 16GB"
    assert first.url == "https://www.publicsurplus.com/sms/auction/1001"
    assert first.price == 120.00
    assert first.bid_count == 3
    assert first.end_time == "09/10/2026 5:00 PM PT"
    assert first.thumbnail_url == "https://images.publicsurplus.com/1001/thumb.jpg"


def test_parse_results_empty_page_returns_empty_list():
    html = read_fixture("no_results.html")
    assert parse_results(html) == []


@responses.activate
def test_search_applies_exclude_keywords_and_max_price():
    query = make_query(exclude_keywords=("case",), max_price=500)
    for page in (1, 2, 3):
        url = build_search_url(query, page)
        body = read_fixture("search_results.html") if page == 1 else read_fixture("no_results.html")
        responses.add(responses.GET, url, body=body, status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = PublicSurplusAdapter(client)
    listings = adapter.search(query)

    ids = {listing.listing_id for listing in listings}
    assert ids == {"1001"}  # 1002 excluded by keyword, 1003 excluded by max_price


@responses.activate
def test_search_stops_pagination_when_a_page_is_empty():
    query = make_query()
    page1_url = build_search_url(query, 1)
    page2_url = build_search_url(query, 2)
    responses.add(responses.GET, page1_url, body=read_fixture("no_results.html"), status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = PublicSurplusAdapter(client)
    listings = adapter.search(query)

    assert listings == []
    assert page2_url not in [call.request.url for call in responses.calls]
    assert len(responses.calls) == 1


@responses.activate
def test_search_respects_page_cap():
    query = make_query()
    for page in (1, 2, 3):
        url = build_search_url(query, page)
        responses.add(responses.GET, url, body=read_fixture("search_results.html"), status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = PublicSurplusAdapter(client, page_cap=3)
    adapter.search(query)

    assert len(responses.calls) == 3
