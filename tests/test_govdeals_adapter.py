import os

import pytest
import responses

from poller.adapters.base import SiteError
from poller.adapters.govdeals import GovDealsAdapter, _category_url, parse_results
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
        category="Computer Equipment",
        state=None,
    )
    defaults.update(overrides)
    return Query(**defaults)


def test_category_url_maps_known_category_case_insensitively():
    url = _category_url(make_query(category="computer EQUIPMENT"))
    assert url == "https://www.govdeals.com/en/computers-parts-supplies"


def test_category_url_raises_for_unmapped_category():
    with pytest.raises(SiteError, match="unmapped category"):
        _category_url(make_query(category="Vehicles"))


def test_category_url_raises_when_no_category_set():
    with pytest.raises(SiteError, match="no category set"):
        _category_url(make_query(category=None))


def test_parse_results_extracts_all_four_real_cards():
    listings = parse_results(read_fixture("search_results.html"))
    assert len(listings) == 4
    ids = {listing.listing_id for listing in listings}
    assert ids == {"30757-69", "30757-39", "4740-9674", "30005-6"}


def test_parse_results_first_card_full_fields():
    listings = parse_results(read_fixture("search_results.html"))
    first = listings[0]
    assert first.site == "govdeals"
    assert first.listing_id == "30757-69"
    assert "Lot of 27 D" in first.title
    assert "Panasonic Toughbook Accessories" in first.title
    assert first.url == "https://www.govdeals.com/en/asset/69/30757"
    assert first.price == 360.0
    assert first.bid_count is None
    assert first.location == "North York, Ontario, CAN"
    assert first.end_time == "September 06, 2026 03:00 PM EDT"
    assert first.thumbnail_url == (
        "https://webassets.lqdt1.com/assets/photos/30757/"
        "30757_69_4b3aef6d-781d-4448-9af7-521414338dc7.jpg?cb=260709141300&w=350&webp=true"
    )


def test_parse_results_reads_price_from_title_attribute_not_currency_text():
    listings = parse_results(read_fixture("search_results.html"))
    usd_listing = next(listing for listing in listings if listing.listing_id == "4740-9674")
    assert usd_listing.price == 25.0  # title="25", text is "USD 25.00"


def test_parse_results_extracts_lazy_loaded_background_image_thumbnail():
    listings = parse_results(read_fixture("search_results.html"))
    lazy_listing = next(listing for listing in listings if listing.listing_id == "30757-39")
    assert lazy_listing.thumbnail_url == (
        "https://webassets.lqdt1.com/assets/photos/30757/"
        "30757_39_7b80bfe5-2208-4ee9-81b4-1535eae4b971.jpg?cb=260508111736&w=350&webp=true"
    )


def test_parse_results_empty_page_returns_empty_list():
    assert parse_results(read_fixture("no_results.html")) == []


@responses.activate
def test_search_applies_keyword_exclude_and_max_price_filters_client_side():
    query = make_query(
        keywords=("ergotron", "cables"),
        exclude_keywords=("adapters",),
        max_price=1000,
    )
    url = _category_url(query)
    responses.add(responses.GET, url, body=read_fixture("search_results.html"), status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = GovDealsAdapter(client)
    listings = adapter.search(query)

    # 30757-69 and 4740-9674 both mention "cables" but also "adapters" (excluded).
    # 30757-39 ("Ergotron...") matches the "ergotron" keyword and has no excluded term.
    # 30005-6 matches no keyword at all.
    ids = {listing.listing_id for listing in listings}
    assert ids == {"30757-39"}


@responses.activate
def test_search_no_keyword_match_returns_empty():
    query = make_query(keywords=("something-nobody-sells",))
    url = _category_url(query)
    responses.add(responses.GET, url, body=read_fixture("search_results.html"), status=200)

    client = RateLimitedClient(min_delay_seconds=0)
    adapter = GovDealsAdapter(client)
    assert adapter.search(query) == []


def test_search_raises_site_error_for_unmapped_category():
    query = make_query(category="Vehicles")
    client = RateLimitedClient(min_delay_seconds=0)
    adapter = GovDealsAdapter(client)
    with pytest.raises(SiteError):
        adapter.search(query)
