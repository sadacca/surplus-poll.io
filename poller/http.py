"""Shared HTTP client with per-site rate limiting (FR6, FR7, FR18)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import requests

from poller.adapters.base import SiteError

logger = logging.getLogger(__name__)

DEFAULT_MIN_DELAY_SECONDS = 2.5
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_READ_TIMEOUT = 30
USER_AGENT = "surplus-poller/0.1 (+https://github.com/)"


class RateLimitedClient:
    """A requests.Session wrapper enforcing a minimum delay between requests
    to the same site, with bounded retry and typed errors for the orchestrator
    to catch and log without aborting the run.
    """

    def __init__(
        self,
        min_delay_seconds: float = DEFAULT_MIN_DELAY_SECONDS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.min_delay_seconds = min_delay_seconds
        self.timeout = (connect_timeout, read_timeout)
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: dict[str, float] = {}

    def _wait_for_rate_limit(self, site: str) -> None:
        last = self._last_request_at.get(site)
        if last is None:
            return
        elapsed = self._clock() - last
        remaining = self.min_delay_seconds - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def get(self, site: str, url: str, **kwargs) -> requests.Response:
        """GET url, enforcing the per-site rate limit and one retry on
        timeout/5xx. Raises SiteError on final failure or non-200/3xx status.
        """
        self._wait_for_rate_limit(site)
        attempts = 0
        last_exc: Exception | None = None
        response: requests.Response | None = None

        while attempts < 2:
            attempts += 1
            self._last_request_at[site] = self._clock()
            try:
                response = self.session.get(url, timeout=self.timeout, **kwargs)
            except requests.Timeout as exc:
                last_exc = exc
                logger.warning("%s: timeout on attempt %d for %s", site, attempts, url)
                continue
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "%s: request error on attempt %d for %s: %s", site, attempts, url, exc
                )
                continue

            if response.status_code >= 500:
                logger.warning(
                    "%s: got %d on attempt %d for %s", site, response.status_code, attempts, url
                )
                self._wait_for_rate_limit(site)
                continue

            break

        if response is None:
            raise SiteError(f"{site}: request failed after {attempts} attempt(s): {last_exc}")

        if response.status_code != 200:
            raise SiteError(f"{site}: got HTTP {response.status_code} for {url}")

        return response
