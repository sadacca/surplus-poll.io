"""PublicSurplus.com search adapter (FR5, FR6).

SELECTOR CAVEAT — read before relying on this adapter in production:
Outbound network access to publicsurplus.com was blocked in the environment
this adapter was developed in, so the CSS selectors and URL parameters below
are a best-effort guess at PublicSurplus's search-results markup, not
something verified against the live site. Everything around the parsing
(URL building, pagination, rate limiting, client-side filtering, error
handling) is real and unit-tested against the synthetic fixture at
tests/fixtures/publicsurplus/search_results.html.

Before trusting this adapter's results, run:
    python -m poller search publicsurplus "<a keyword you expect matches for>"
against the live site, save the HTML of a results page, and update
SEARCH_URL / _ROW_SELECTOR / _parse_row (and the fixture, so the tests keep
covering the real structure) to match what you see.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from poller.adapters.base import SiteError
from poller.http import RateLimitedClient
from poller.models import Listing, Query

logger = logging.getLogger(__name__)

SITE_NAME = "publicsurplus"
SEARCH_URL = "https://www.publicsurplus.com/sms/browse/search"
DEFAULT_PAGE_CAP = 3

# TODO(unverified): confirm against a live results page.
_ROW_SELECTOR = "tr.AuctionRow"
_TITLE_SELECTOR = "a.ItemTitle"
_PRICE_SELECTOR = ".CurrentPrice"
_BID_COUNT_SELECTOR = ".BidCount"
_END_TIME_SELECTOR = ".EndTime"
_THUMB_SELECTOR = "img.Thumb"

_LISTING_ID_RE = re.compile(r"/auction/(\d+)")
_PRICE_RE = re.compile(r"[\d,]+\.?\d*")
_INT_RE = re.compile(r"\d+")


class PublicSurplusAdapter:
    name = SITE_NAME

    def __init__(self, client: RateLimitedClient, page_cap: int = DEFAULT_PAGE_CAP):
        self.client = client
        self.page_cap = page_cap

    def search(self, query: Query) -> list[Listing]:
        all_listings: list[Listing] = []
        for page in range(1, self.page_cap + 1):
            url = build_search_url(query, page)
            response = self.client.get(SITE_NAME, url)
            try:
                page_listings = parse_results(response.text)
            except Exception as exc:  # noqa: BLE001 - convert any parse failure to SiteError
                raise SiteError(f"{SITE_NAME}: failed to parse results for {url}: {exc}") from exc

            if not page_listings:
                break
            all_listings.extend(page_listings)

        return [
            listing
            for listing in all_listings
            if _passes_client_side_filters(listing, query)
        ]


def build_search_url(query: Query, page: int) -> str:
    params = {
        "searchtext": " ".join(query.keywords),
        "page": str(page),
    }
    if query.category:
        params["category"] = query.category
    if query.state:
        params["state"] = query.state
    query_string = "&".join(f"{k}={_url_quote(v)}" for k, v in params.items())
    return f"{SEARCH_URL}?{query_string}"


def _url_quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


def parse_results(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(_ROW_SELECTOR)
    return [row for row in (_parse_row(r) for r in rows) if row is not None]


def _parse_row(row) -> Listing | None:
    title_el = row.select_one(_TITLE_SELECTOR)
    if title_el is None:
        return None

    href = title_el.get("href", "")
    match = _LISTING_ID_RE.search(href)
    listing_id = match.group(1) if match else href

    url = href if href.startswith("http") else f"https://www.publicsurplus.com{href}"

    price = _parse_price(_text(row.select_one(_PRICE_SELECTOR)))
    bid_count = _parse_int(_text(row.select_one(_BID_COUNT_SELECTOR)))
    end_time = _text(row.select_one(_END_TIME_SELECTOR)) or None

    thumb_el = row.select_one(_THUMB_SELECTOR)
    thumbnail_url = thumb_el.get("src") if thumb_el is not None else None

    return Listing(
        site=SITE_NAME,
        listing_id=listing_id,
        title=title_el.get_text(strip=True),
        url=url,
        price=price,
        bid_count=bid_count,
        thumbnail_url=thumbnail_url,
        end_time=end_time,
    )


def _text(el) -> str:
    return el.get_text(strip=True) if el is not None else ""


def _parse_price(text: str) -> float | None:
    match = _PRICE_RE.search(text)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def _parse_int(text: str) -> int | None:
    match = _INT_RE.search(text)
    if not match:
        return None
    return int(match.group(0))


def _passes_client_side_filters(listing: Listing, query: Query) -> bool:
    title_lower = listing.title.lower()
    for excluded in query.exclude_keywords:
        if excluded.lower() in title_lower:
            return False
    has_cap = query.max_price is not None and listing.price is not None
    if has_cap and listing.price > query.max_price:
        return False
    return True
