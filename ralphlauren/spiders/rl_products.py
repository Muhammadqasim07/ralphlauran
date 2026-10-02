"""Spider for the Ralph Lauren PK storefront (https://www.ralphlauren.global/pk/en).

Crawls every category page reachable from the site navigation. Parsing is
done by the ``ListingPage`` page object (see ralphlauren/pages.py), which
scrapy-poet injects into ``parse_listing``. Pages are downloaded through
Zyte API with browser rendering (the site 403s plain HTTP) and Zyte API
sessions (see settings.py).

Usage:
    scrapy crawl rl_products -o products.jsonl

Limit the crawl to categories whose URL contains a substring:
    scrapy crawl rl_products -a include=casual-shirts -o shirts.jsonl

Cap API spend while testing:
    scrapy crawl rl_products -s CLOSESPIDER_PAGECOUNT=5

Pagination: listing pages render 30 tiles server-side and further pages
live at ?page=N on the same URL; the spider follows them until the site's
"N Items" count is reached (or max_pages caps the loop).
"""

from scrapy import Request, Spider
from scrapy.linkextractors import LinkExtractor
from w3lib.url import add_or_replace_parameter

from ..pages import ListingPage

# Site serves full pages only to real browsers; everything else gets 403.
AUTOMAP = {"zyte_api_automap": {"browserHtml": True}}

# The site server-renders grids in batches of 30 tiles.
PAGE_BATCH = 30

# Category URLs look like /pk/en/men/clothing/casual-shirts/10202 —
# a path under /pk/en ending in a numeric category id.
CATEGORY_RE = r"/pk/en/[a-z0-9-]+(?:/[a-z0-9-]+)*/\d+"


class RlProductsSpider(Spider):
    name = "rl_products"
    allowed_domains = ["ralphlauren.global"]
    start_urls = ["https://www.ralphlauren.global/pk/en"]

    # Class attribute so the exact extraction rules can be reused in tests.
    link_extractor = LinkExtractor(
        allow=CATEGORY_RE,
        deny=(
            r"\.html",  # product detail pages
            r"start=",  # pagination echoes
            r"accountlogin|stores|wishlist|cart|checkout",
        ),
    )

    def __init__(self, include=None, category=None, max_pages=50, *args, **kwargs):
        """``include`` limits the crawl to category URLs containing the
        given substring, e.g. ``-a include=men/clothing``; ``category``
        restricts the crawl to the one category whose URL ends with the
        given slug or id, e.g. ``-a category=10202``; ``max_pages`` caps
        how many grid pages to fetch per category."""
        super().__init__(*args, **kwargs)
        self.include = include.lower() if include else None
        self.category = category.rstrip("/").lower() if category else None
        self.max_pages = max(1, int(max_pages))

    async def start(self):
        # Scrapy >= 2.13 consumes Spider.start(); start_requests() is no
        # longer called by the engine.
        for url in self.start_urls:
            yield Request(url, meta=dict(AUTOMAP), dont_filter=True)

    def parse(self, response):
        """Homepage (or any non-category page): discover category links."""
        yield from self.follow_categories(response)

    def parse_listing(
        self, response, listing_page: ListingPage, page=1, collected=0, total=None
    ):
        """Category listing page: items come from the injected page object;
        further grid pages live at ?page=N (verified live — start=/sz= are
        ignored by the site), so keep paginating until the site's item
        count is reached. Page 1 also discovers further categories."""
        self.logger.info("Listing %s (page %d)", response.url, page)
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
                meta=dict(AUTOMAP),
            )

    def follow_categories(self, response):
        for link in self.link_extractor.extract_links(response):
            url = link.url.split("?", 1)[0]  # strip ?ab= tracking params
            if self.category and not url.rstrip("/").lower().endswith(self.category):
                continue
            if self.include and self.include not in url.lower():
                continue
            yield response.follow(url, callback=self.parse_listing, meta=dict(AUTOMAP))
