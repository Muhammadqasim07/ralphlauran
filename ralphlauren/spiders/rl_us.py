"""Spider for the Ralph Lauren US storefront (https://www.ralphlauren.com),
scoped to a US zip code, with full pagination of every category.

How the zip scoping works (all steps verified against the live site):

1. A pool of Zyte API sessions is warmed with a browser request to the
   homepage. Sessions MUST be born as browser requests — sessions created
   by plain-HTTP requests cannot be reused by browserHtml requests later
   (Zyte API rejects them with 422 "Session has expired").
2. For each session, the zip code is POSTed once to the site's own
   StoreInventory-SetZipCode endpoint (the same call the site's "enter
   your zip" UI makes) — a cheap plain-HTTP request through the same
   session, which the site ties to the session cookies.
3. Every category page is then fetched with browserHtml through one of
   the zip-scoped sessions, so the site serves listings for that
   delivery location.

How pagination works (verified against the live site): listing pages
render their first 30 tiles server-side, and further batches live at
``?page=N`` on the same URL (NOT ``?start=`` — the app ignores start/sz).
The spider follows ?page=2, ?page=3, … until the site's "N Items" count
is reached, an empty/short page arrives, or max_pages stops the loop.

This spider manages its sessions itself, so it disables the scrapy-zyte-api
session middleware (see custom_settings); the PK spider (rl_products)
keeps using it.

Usage — one category, all products:
    scrapy crawl rl_us -a zip_code=10001 -a category=men-big-and-tall-casual-shirts -o cat.jsonl

All categories:
    scrapy crawl rl_us -a zip_code=10001 -o products.jsonl

Substring category filter:
    scrapy crawl rl_us -a zip_code=10001 -a include=casual-shirts -o shirts.jsonl

Cap API spend while testing:
    scrapy crawl rl_us -a zip_code=10001 -s CLOSESPIDER_PAGECOUNT=10

Notes:
- US category URLs are clean slugs, e.g. /men-big-and-tall-casual-shirts
  (no numeric id like on the global/PK storefront), so the category link
  rule differs from the PK spider (rl_products).
"""

import base64
import re
from uuid import uuid4

from scrapy import Request, Spider
from scrapy.linkextractors import LinkExtractor
from w3lib.url import add_or_replace_parameter

from ..pages import ListingPage

BASE = "https://www.ralphlauren.com"
SET_ZIP_URL = (
    BASE
    + "/on/demandware.store/Sites-RalphLauren_US-Site/en_US/StoreInventory-SetZipCode"
)

# The site server-renders grids in batches of 30 tiles.
PAGE_BATCH = 30

# US category URLs are single-segment slugs starting with a department,
# e.g. /men-big-and-tall-casual-shirts, /boys-clothing-polo-shirts.
# Require the department plus at least two more path words, so top-level
# landings (/men) and editorial pages (/brands-polo-...) stay out.
CATEGORY_RE = (
    r"ralphlauren\.com/(?:men|women|boys|girls|kids|baby|home)"
    r"(?:-[a-z0-9]+){2,}/?$"
)


def browser_params(session_id=None):
    """Zyte API params for a browser-rendered request, optionally pinned
    to one of our zip-scoped sessions."""
    params = {"browserHtml": True, "geolocation": "us"}
    if session_id:
        params["session"] = {"id": session_id}
    return params


def zip_post_params(session_id, zip_code):
    """Zyte API params for the zip POST (plain HTTP, same session)."""
    return {
        "httpResponseBody": True,
        "httpRequestMethod": "POST",
        "httpRequestBody": base64.b64encode(f"zipCode={zip_code}".encode()).decode(),
        "customHttpRequestHeaders": [
            {"name": "X-Requested-With", "value": "XMLHttpRequest"},
            {"name": "Content-Type", "value": "application/x-www-form-urlencoded"},
        ],
        "geolocation": "us",
        "session": {"id": session_id},
    }


class RlUsSpider(Spider):
    name = "rl_us"
    allowed_domains = ["ralphlauren.com"]
    start_urls = [BASE + "/"]

    custom_settings = {
        # This spider manages its own Zyte API sessions (see start),
        # so the scrapy-zyte-api session middleware must not layer its own
        # sessions on top.
        "ZYTE_API_SESSION_ENABLED": False,
    }

    # Class attribute so the exact extraction rules can be reused in tests.
    link_extractor = LinkExtractor(
        allow=CATEGORY_RE,
        deny=(
            r"\.html",  # product detail pages
            r"demandware",  # SFCC ajax endpoints
            r"accountlogin|stores|wishlist|cart|checkout|customerservice",
        ),
    )

    def __init__(
        self,
        zip_code=None,
        include=None,
        category=None,
        pool_size=4,
        max_pages=50,
        *args,
        **kwargs,
    ):
        """``zip_code`` scopes the crawl to a US delivery location (5
        digits, e.g. 10001); ``category`` restricts the crawl to the one
        category whose URL ends with the given slug (e.g.
        men-big-and-tall-casual-shirts); ``include`` limits the crawl to
        category URLs containing the given substring; ``pool_size`` sets
        how many zip-scoped sessions to keep; ``max_pages`` caps how many
        grid pages to fetch per category."""
        super().__init__(*args, **kwargs)
        if not zip_code or not re.fullmatch(r"\d{5}", zip_code):
            raise ValueError("a 5-digit US zip code is required: -a zip_code=10001")
        self.zip_code = zip_code
        self.include = include.lower() if include else None
        self.category = category.rstrip("/").lower() if category else None
        self.pool_size = max(1, int(pool_size))
        self.max_pages = max(1, int(max_pages))
        # Session ids whose zip POST was confirmed, and a round-robin
        # counter for spreading listing requests over the pool.
        self.sessions = []
        self._rr = 0
        self._links_yielded = False

    # ------------------------------------------------------------- warmup
    async def start(self):
        """Birth every session with a browser homepage request."""
        for _ in range(self.pool_size):
            sid = str(uuid4())
            yield Request(
                BASE + "/",
                meta={"zyte_api": browser_params(sid), "dont_merge_cookies": True},
                callback=self._on_session_home,
                cb_kwargs={"sid": sid},
                dont_filter=True,
            )

    def _on_session_home(self, response, sid):
        # Stash category URLs from the first homepage; after the zip POST
        # for this session is confirmed, the crawl can start through it.
        urls = [] if self._links_yielded else self.category_urls(response)
        yield Request(
            SET_ZIP_URL,
            method="POST",
            meta={
                "zyte_api": zip_post_params(sid, self.zip_code),
                "dont_merge_cookies": True,
            },
            callback=self._on_zip_set,
            cb_kwargs={"sid": sid, "urls": urls},
            dont_filter=True,
        )

    def _on_zip_set(self, response, sid, urls):
        # The SFCC endpoint returns JSON, which scrapy delivers as a plain
        # (non-text) Response — read .body, not .text.
        body = response.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        if self.zip_code in body:
            self.sessions.append(sid)
            self.logger.info("Session %s… zip-scoped to %s", sid[:8], self.zip_code)
        else:
            self.logger.warning(
                "Zip %s NOT confirmed for session %s…: %r — its requests "
                "will run without a zip scope",
                self.zip_code,
                sid[:8],
                body[:80],
            )
        if urls:
            self._links_yielded = True
            for url in urls:
                yield self._listing_request(url)

    # ------------------------------------------------------------ crawling
    def parse_listing(
        self, response, listing_page: ListingPage, page=1, collected=0, total=None
    ):
        """Category listing page: items come from the injected page object;
        further grid pages live at ?page=N, so keep paginating until the
        site's item count is reached (page 1 also discovers categories)."""
        items = list(listing_page.to_items())

        # Trust the freshest "N Items" count, and backfill it onto items
        # from pages whose HTML did not include it.
        page_total = listing_page.total_in_category
        if page_total:
            total = page_total
        for item in items:
            if not item.get("total_in_category") and total:
                item["total_in_category"] = total
        yield from items

        if page == 1:
            yield from self.follow_categories(response)

        collected += len(items)
        more_pages = total is not None and collected < total
        if total is None:
            # No count available: assume another full batch means more pages.
            more_pages = len(items) >= PAGE_BATCH
        if items and more_pages and page < self.max_pages:
            yield Request(
                add_or_replace_parameter(response.url, "page", str(page + 1)),
                callback=self.parse_listing,
                cb_kwargs={"page": page + 1, "collected": collected, "total": total},
                # Stay on the session that served this page (zip-scoped).
                meta={
                    "zyte_api": browser_params(self._response_session(response)),
                    "dont_merge_cookies": True,
                },
            )

    def category_urls(self, response):
        """Category links on a page, query strings and the ``category`` /
        ``include`` filters applied."""
        urls = []
        for link in self.link_extractor.extract_links(response):
            url = link.url.split("?", 1)[0]  # strip tracking params
            if self.category and not url.rstrip("/").lower().endswith(self.category):
                continue
            if self.include and self.include not in url.lower():
                continue
            urls.append(url)
        return urls

    def follow_categories(self, response):
        for url in self.category_urls(response):
            yield self._listing_request(url)

    def _listing_request(self, url):
        return Request(
            url,
            callback=self.parse_listing,
            meta={
                "zyte_api": browser_params(self._next_session()),
                "dont_merge_cookies": True,
            },
        )

    def _next_session(self):
        """Round-robin over the zip-scoped sessions; None (unscoped) if
        the pool is still empty."""
        if not self.sessions:
            return None
        sid = self.sessions[self._rr % len(self.sessions)]
        self._rr += 1
        return sid

    @staticmethod
    def _response_session(response):
        """The Zyte API session id that served *response*, if any."""
        zyte = response.meta.get("zyte_api") or {}
        session = zyte.get("session") or {}
        return session.get("id")
