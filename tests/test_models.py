from poller.models import Listing, Match, Query


def test_listing_key_is_site_and_id():
    listing = Listing(site="publicsurplus", listing_id="123", title="GPU", url="http://x")
    assert listing.key == ("publicsurplus", "123")


def test_query_construction_defaults():
    q = Query(
        id="gpu-search",
        label="Server GPUs",
        enabled=True,
        sites=("publicsurplus", "govdeals"),
        keywords=("nvidia", "gpu"),
    )
    assert q.exclude_keywords == ()
    assert q.max_price is None
    assert q.notify == ()


def test_match_pairs_listing_and_query():
    q = Query(id="q1", label="Q1", enabled=True, sites=("publicsurplus",), keywords=("gpu",))
    listing = Listing(site="publicsurplus", listing_id="1", title="GPU", url="http://x")
    m = Match(listing=listing, query=q)
    assert m.listing.key == ("publicsurplus", "1")
    assert m.query.id == "q1"
