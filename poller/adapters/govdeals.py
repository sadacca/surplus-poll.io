"""GovDeals.com search adapter (FR5, FR6).

VERIFIED (2026-09-03) against a real, live page saved by the repo owner:
https://www.govdeals.com/en/computers-parts-supplies — a category browse
page. Confirmed:
- The site is Angular Universal (server-side rendered): listing cards are
  present in the raw HTML with no JS execution needed, satisfying FR6.
- Card structure: `_ROW_SELECTOR` and friends below, including that a
  listing's thumbnail is a plain `<img src>` only for the first few cards;
  the rest lazy-load as a `background-image: url(...)` inline style on the
  same element instead (`_extract_thumbnail_url` handles both).
- `.card-amount`'s `title` attribute holds the raw numeric price (no
  currency prefix/thousands separator to strip), more reliable than its
  text content ("CAD 360.00" / "USD 25.00" — GovDeals serves both US and
  Canadian listings).
- No per-listing bid count is rendered on this card view (only current
  price), so `bid_count` is always None for GovDeals listings.
- The card's `id` attribute (`asset-<lotId>-<itemId>`) is a stable,
  already-unique identifier — used directly as `listing_id` instead of
  parsing it out of the href.

STILL UNVERIFIED — this is the gap, not a finished contract:
- There is no confirmed keyword-search URL. The capture above is a
  category browse page with no search term in it; a prior guess at
  `/search?keywords=...` returned HTTP 403 in production (see the run at
  https://github.com/sadacca/surplus-poll.io/actions/runs/33729955405),
  which is consistent with that path simply not existing behind GovDeals's
  edge/WAF rather than a bot-block. Until a real keyword-search results
  page is captured the same way, this adapter only supports browsing a
  known category page and filtering by keyword client-side (see
  `_CATEGORY_SLUGS`) — a query with no mapped `category` fails clearly
  with a SiteError rather than guessing another URL that might also 403.
- Pagination is unverified too (this one page already returned 120 cards
  in a single response, whether from a generous page size or preloaded
  infinite scroll) — `DEFAULT_PAGE_CAP` is 1 until that's confirmed.

To extend the category mapping or verify search/pagination: capture a
keyword search results page the same way (browser -> search -> Save As
-> Webpage, Single File / MHTML) and update `_CATEGORY_SLUGS` and this
docstring accordingly.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from poller.adapters.base import SiteError
from poller.http import RateLimitedClient
from poller.models import Listing, Query

logger = logging.getLogger(__name__)

SITE_NAME = "govdeals"
BASE_URL = "https://www.govdeals.com"
DEFAULT_PAGE_CAP = 1

# Maps a query's free-text `category` (as used in queries.yaml) to a
# verified GovDeals category-browse URL slug. Add to this as more
# categories get confirmed the same way "Computer Equipment" was.
_CATEGORY_SLUGS = {
    "computer equipment": "computers-parts-supplies",
}

_ROW_SELECTOR = "div.card.card-horizontal"
_TITLE_SELECTOR = "p.card-title a"
_PRICE_SELECTOR = ".card-amount"
_LOCATION_SELECTOR = '[name="pAssetLocation"]'
_TIMER_SPAN_SELECTOR = "app-ux-timer .timerAttribute > span"
_THUMB_CONTAINER_SELECTOR = ".card-listview"

_BG_IMAGE_URL_RE = re.compile(r'background-image:\s*url\((["\']?)(.*?)\1\)')
_PRICE_RE = re.compile(r"[\d,]+\.?\d*")


class GovDealsAdapter:
    name = SITE_NAME

    def __init__(self, client: RateLimitedClient, page_cap: int = DEFAULT_PAGE_CAP):
        self.client = client
        self.page_cap = page_cap

    def search(self, query: Query) -> list[Listing]:
        base_url = _category_url(query)

        all_listings: list[Listing] = []
        for page in range(1, self.page_cap + 1):
            url = base_url if page == 1 else f"{base_url}?page={page}"
            response = self.client.get(SITE_NAME, url)
            try:
                page_listings = parse_results(response.text)
            except Exception as exc:  # noqa: BLE001 - convert any parse failure to SiteError
                raise SiteError(f"{SITE_NAME}: failed to parse results for {url}: {exc}") from exc

            if not page_listings:
                break
            all_listings.extend(page_listings)

        return [listing for listing in all_listings if _passes_client_side_filters(listing, query)]


def _category_url(query: Query) -> str:
    if not query.category:
        raise SiteError(
            f"{SITE_NAME}: query {query.id!r} has no category set, and this adapter can only "
            f"browse a known category page (no verified keyword-search URL exists yet — see "
            f"the module docstring). Known categories: {sorted(_CATEGORY_SLUGS)}"
        )
    slug = _CATEGORY_SLUGS.get(query.category.strip().lower())
    if slug is None:
        raise SiteError(
            f"{SITE_NAME}: unmapped category {query.category!r} for query {query.id!r}. "
            f"Known categories: {sorted(_CATEGORY_SLUGS)}"
        )
    return f"{BASE_URL}/en/{slug}"


def parse_results(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(_ROW_SELECTOR)
    return [row for row in (_parse_row(r) for r in rows) if row is not None]


def _parse_row(row) -> Listing | None:
    title_el = row.select_one(_TITLE_SELECTOR)
    if title_el is None:
        return None

    href = title_el.get("href", "")
    listing_id = (row.get("id") or "").removeprefix("asset-") or href

    title = title_el.get("title") or title_el.get_text(strip=True)

    price_el = row.select_one(_PRICE_SELECTOR)
    price = _parse_price(price_el)

    loc_el = row.select_one(_LOCATION_SELECTOR)
    location = loc_el.get_text(strip=True) if loc_el is not None else None

    end_time = _extract_end_time(row)
    thumbnail_url = _extract_thumbnail_url(row)

    return Listing(
        site=SITE_NAME,
        listing_id=listing_id,
        title=title,
        url=href,
        price=price,
        bid_count=None,  # not exposed on the category-browse card view
        thumbnail_url=thumbnail_url,
        end_time=end_time,
        location=location,
    )


def _parse_price(price_el) -> float | None:
    if price_el is None:
        return None
    title_attr = price_el.get("title")
    if title_attr:
        try:
            return float(title_attr.replace(",", ""))
        except ValueError:
            pass
    match = _PRICE_RE.search(price_el.get_text(strip=True))
    return float(match.group(0).replace(",", "")) if match else None


def _extract_end_time(row) -> str | None:
    spans = row.select(_TIMER_SPAN_SELECTOR)
    if not spans:
        return None
    text = spans[-1].get_text(strip=True)
    return text.strip("()") or None


def _extract_thumbnail_url(row) -> str | None:
    container = row.select_one(_THUMB_CONTAINER_SELECTOR)
    if container is None:
        return None
    img = container if container.name == "img" else container.select_one("img")
    if img is not None and img.get("src"):
        return img["src"]
    style = container.get("style", "")
    match = _BG_IMAGE_URL_RE.search(style)
    return match.group(2) if match else None


def _passes_client_side_filters(listing: Listing, query: Query) -> bool:
    title_lower = listing.title.lower()

    if query.keywords and not any(kw.lower() in title_lower for kw in query.keywords):
        return False

    for excluded in query.exclude_keywords:
        if excluded.lower() in title_lower:
            return False

    has_cap = query.max_price is not None and listing.price is not None
    if has_cap and listing.price > query.max_price:
        return False

    return True
