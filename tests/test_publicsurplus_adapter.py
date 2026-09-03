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
        keywords=("dell", "optiplex"),
        exclude_keywords=(),
        max_price=None,
        category=None,
        state=None,
        zip=None,
        radius_miles=None,
    )
    defaults.update(overrides)
    return Query(**defaults)


def test_build_search_url_uses_real_params():
    url = build_search_url(make_query(), page=1)
    assert url.startswith("https://m.publicsurplus.com/sms/browse/search?")
    assert "keyWord=dell+optiplex" in url
    assert "page=0" in url  # 0-indexed on the real site
    assert "catId=-1" in url
    assert "search=Search" in url


def test_build_search_url_page_is_zero_indexed():
    assert "page=0" in build_search_url(make_query(), page=1)
    assert "page=1" in build_search_url(make_query(), page=2)
    assert "page=2" in build_search_url(make_query(), page=3)


def test_build_search_url_includes_zip_and_radius():
    url = build_search_url(make_query(zip="94103", radius_miles=200), page=1)
    assert "zipCode=94103" in url
    assert "milesLocation=200" in url


def test_parse_results_extracts_all_four_real_items():
    listings = parse_results(read_fixture("search_results.html"))
    assert len(listings) == 4
    ids = {listing.listing_id for listing in listings}
    assert ids == {"4075668", "4076008", "4075967", "4079427"}


def test_parse_results_first_item_full_fields():
    listings = parse_results(read_fixture("search_results.html"))
    first = listings[0]
    assert first.site == "publicsurplus"
    assert first.listing_id == "4075668"
    assert first.title == "16 Dell OptiPlex Micro PCs - TJB - Z8"  # "#4075668 - " prefix stripped
    assert first.url == "https://m.publicsurplus.com/sms/auction/view?auc=4075668"
    assert first.price == 730.0
    assert first.bid_count is None
    assert first.location == "FL"
    assert first.end_time == "11 hours 31 mins"
    assert first.thumbnail_url == (
        "https://d37qv0n5b4mbzm.cloudfront.net/sms/docviewer/cdnmainaucdoc/thumb-s/4075668/71601737"
    )


def test_parse_results_handles_comma_thousands_in_price():
    listings = parse_results(read_fixture("search_results.html"))
    second = next(listing for listing in listings if listing.listing_id == "4076008")
    assert second.price == 2375.0  # "$2,375.00"


def test_parse_results_empty_page_returns_empty_list():
    assert parse_results(read_fixture("no_results.html")) == []


@responses.activate
def test_search_applies_exclude_keywords_max_price_and_state_filters():
    query = make_query(exclude_keywords=("pallet",), max_price=1000, state="FL")
    for page in (1, 2, 3):
        url = build_search_url(query, page)
        body = read_fixture("search_results.html") if page == 1 else read_fixture("no_results.html")
        responses.add(responses.GET, url, body=body, status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = PublicSurplusAdapter(client)
    listings = adapter.search(query)

    # 4075668 (FL, $730) passes; 4076008 (FL, $2375) fails max_price;
    # 4075967 (AZ) fails state; 4079427 (CA) fails state.
    ids = {listing.listing_id for listing in listings}
    assert ids == {"4075668"}


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
