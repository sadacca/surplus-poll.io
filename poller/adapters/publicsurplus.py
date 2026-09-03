"""PublicSurplus.com search adapter (FR5, FR6).

VERIFIED (2026-09-03) against a real, live search results page saved by
the repo owner:
https://m.publicsurplus.com/sms/browse/search?posting=y&slth=&page=0&sortBy=&keyWord=Dell+optiplex&catId=-1&endHours=-1&startHours=-1&lowerPrice=0&higherPrice=0&milesLocation=-1&zipCode=&region=&search=Search
Confirmed:
- Search lives on the **mobile** subdomain, `m.publicsurplus.com` (not
  `www`), at `/sms/browse/search`, and is plain server-rendered HTML — no
  JS needed (satisfies FR6). It's also much simpler markup than the
  desktop site would likely be, which is a bonus.
- Real query params (see `build_search_url`): `keyWord` (not `searchtext`),
  `page` is **0-indexed**, `zipCode`/`milesLocation` are real filter
  params matching Query.zip/radius_miles directly, `catId=-1` means "all
  categories". `lowerPrice`/`higherPrice` exist but their effect wasn't
  confirmed by this capture (both were 0 in it) — max_price stays a
  client-side filter, same as before, rather than risk relying on an
  unconfirmed server param.
- Card structure: one `div.auctionItem` per listing, confirmed against
  all 17 items on the captured page (see `_ROW_SELECTOR` and friends). No
  bid count is shown on this view (`bid_count` is always None). "Time
  Left" is a relative countdown ("11 hours 31 mins"), not an absolute
  timestamp like GovDeals's — `end_time` is stored as that raw text.
- State (e.g. "FL") is scraped per-listing and applied as a client-side
  filter against `Query.state`, since the URL has no state param.

STILL UNVERIFIED / not wired up:
- `category` (Query.category) does nothing here: PublicSurplus categories
  are numeric IDs (`catId`), and no real mapping from a category name to
  an ID has been captured yet. `catId=-1` (all categories) is always sent.
- Pagination beyond page 0: untested. `page` being present and 0-indexed
  is confirmed by the capture; whether page 1, 2, ... return more results
  in the expected shape has not been checked against a real response.

To extend: capture a keyword search with a category filter applied (to
get a real catId), or a page 2+ URL, the same way this one was (browser
-> search -> Save As -> Webpage/MHTML) and update this docstring plus
`build_search_url` accordingly.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from poller.adapters.base import SiteError
from poller.http import RateLimitedClient
from poller.models import Listing, Query

logger = logging.getLogger(__name__)

SITE_NAME = "publicsurplus"
BASE_URL = "https://m.publicsurplus.com"
SEARCH_PATH = "/sms/browse/search"
DEFAULT_PAGE_CAP = 3

_ROW_SELECTOR = ".auctionItem"
_LISTING_LINK_SELECTOR = ".auctionItemR a[href*='auction/view']"
_TEXT_BLOCK_SELECTOR = ".auctionItemR"
_THUMB_SELECTOR = ".auctionItemL img"

_TITLE_PREFIX_RE = re.compile(r"^#\d+\s*-\s*")
_STATE_RE = re.compile(r"State:\s*(\S*)")
_PRICE_RE = re.compile(r"Current Price:\s*\$?([\d,]+\.?\d*)")
_TIME_LEFT_RE = re.compile(r"Time Left:\s*(.+)$")


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

        return [listing for listing in all_listings if _passes_client_side_filters(listing, query)]


def build_search_url(query: Query, page: int) -> str:
    params = {
        "posting": "y",
        "slth": "",
        "page": str(page - 1),  # the site is 0-indexed
        "sortBy": "",
        "keyWord": " ".join(query.keywords),
        "catId": "-1",  # category filtering isn't wired up yet; see module docstring
        "endHours": "-1",
        "startHours": "-1",
        "lowerPrice": "0",
        "higherPrice": "0",
        "milesLocation": str(query.radius_miles) if query.radius_miles is not None else "-1",
        "zipCode": query.zip or "",
        "region": "",
        "search": "Search",
    }
    query_string = "&".join(f"{k}={_url_quote(v)}" for k, v in params.items())
    return f"{BASE_URL}{SEARCH_PATH}?{query_string}"


def _url_quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value)


def parse_results(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(_ROW_SELECTOR)
    return [row for row in (_parse_row(r) for r in rows) if row is not None]


def _parse_row(row) -> Listing | None:
    link_el = row.select_one(_LISTING_LINK_SELECTOR)
    if link_el is None:
        return None

    href = link_el.get("href", "")
    listing_id = parse_qs(urlparse(href).query).get("auc", [href])[0]
    title = _TITLE_PREFIX_RE.sub("", link_el.get_text(strip=True))

    text_block = row.select_one(_TEXT_BLOCK_SELECTOR)
    block_text = text_block.get_text(" ", strip=True) if text_block is not None else ""

    state_match = _STATE_RE.search(block_text)
    location = state_match.group(1) or None if state_match else None

    price_match = _PRICE_RE.search(block_text)
    price = float(price_match.group(1).replace(",", "")) if price_match else None

    time_left_match = _TIME_LEFT_RE.search(block_text)
    end_time = time_left_match.group(1).strip() if time_left_match else None

    thumb_el = row.select_one(_THUMB_SELECTOR)
    thumbnail_url = thumb_el.get("src") if thumb_el is not None else None

    return Listing(
        site=SITE_NAME,
        listing_id=listing_id,
        title=title,
        url=href,
        price=price,
        bid_count=None,  # not shown on the mobile search results view
        thumbnail_url=thumbnail_url,
        end_time=end_time,
        location=location,
    )


def _passes_client_side_filters(listing: Listing, query: Query) -> bool:
    title_lower = listing.title.lower()

    for excluded in query.exclude_keywords:
        if excluded.lower() in title_lower:
            return False

    has_cap = query.max_price is not None and listing.price is not None
    if has_cap and listing.price > query.max_price:
        return False

    if query.state and listing.location and listing.location.lower() != query.state.lower():
        return False

    return True
