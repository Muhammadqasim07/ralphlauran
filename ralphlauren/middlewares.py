"""Downloader middlewares for the ralphlauren project.

Two pieces live here:

- ``BlockPageRetryMiddleware``: retries requests whose responses look
  like anti-bot blocks (some arrive with HTTP 200, so status alone is
  not enough).
- ``RalphlaurenSessionChecker``: wired into scrapy-zyte-api session
  management via the ``ZYTE_API_SESSION_CHECKER`` setting; it tells the
  framework whether a session is still healthy after each response.

The Zyte API and scrapy-poet middlewares (download handler, sessions,
dependency injection) are installed automatically by their addons —
see ADDONS in settings.py.
"""

from scrapy.downloadermiddlewares.retry import get_retry_request
from scrapy.exceptions import IgnoreRequest

# Markers that appear on block/interstitial pages even when the HTTP
# status is 200. Checked against the start of the body, lowercased.
BLOCK_MARKERS = (
    "access denied",
    "pardon our interruption",
    "please verify you are a human",
    "request unsuccessful",
)

BLOCK_STATUSES = (401, 403, 429)


def looks_blocked(response) -> bool:
    """Heuristic: does this response look like an anti-bot block page?"""
    if response.status in BLOCK_STATUSES:
        return True
    body = getattr(response, "text", "") or ""
    head = body[:10_000].lower()
    return any(marker in head for marker in BLOCK_MARKERS)


class BlockPageRetryMiddleware:
    """Retry requests whose responses look like blocks.

    After ``max_retries`` attempts the response is dropped with
    ``IgnoreRequest`` so the crawl does not store garbage.
    """

    max_retries = 2

    def __init__(self, stats=None):
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.stats)

    def process_response(self, request, response, spider):
        if not looks_blocked(response):
            return response

        self.stats.inc_value("blockpage/hits")
        retry = get_retry_request(
            request,
            reason="block page",
            spider=spider,
            max_retry_times=self.max_retries,
        )
        if retry is None:
            self.stats.inc_value("blockpage/given_up")
            spider.logger.error(
                "Blocked %s, giving up after %d retries", request.url, self.max_retries
            )
            raise IgnoreRequest(f"block page: {request.url}")
        self.stats.inc_value("blockpage/retries")
        return retry


class RalphlaurenSessionChecker:
    """Session health checker for Zyte API sessions.

    scrapy-zyte-api calls ``check()`` with each response fetched through a
    session: return ``True`` to keep the session (same IP + cookie jar for
    following requests), ``False`` to discard it and open a fresh one.
    """

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def check(self, response, request) -> bool:
        return not looks_blocked(response)
