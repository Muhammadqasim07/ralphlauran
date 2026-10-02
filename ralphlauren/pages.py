"""Page objects for the Ralph Lauren PK storefront.

A page object owns ALL the parsing for one page type; the spider only
navigates (see spiders/rl_products.py). scrapy-poet injects these into
spider callbacks based on their type annotations, building each one from
the downloaded response. Because parsing lives here and depends only on a
response, it can be unit-tested offline against a saved HTML fixture.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from web_poet import WebPage

from .items import ProductItem

TILE_SELECTOR = "div.product-tile.js-product-tile"

# Price symbols seen on Ralph Lauren storefronts, mapped to ISO codes.
CURRENCY_SYMBOLS = (("$", "USD"), ("Rs", "PKR"), ("£", "GBP"), ("€", "EUR"))


class ListingPage(WebPage):
    """A category listing page, i.e. a grid of product tiles."""

    def to_items(self):
        """Yield one ``ProductItem`` per unique product tile on the page."""
        total = self.total_in_category
        seen = set()
        for tile in self.response.css(TILE_SELECTOR):
            product_id = tile.attrib.get("data-masterid")
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            yield self._item(tile, total)

    def _item(self, tile, total):
        price_parts = [
            t.strip()
            for t in tile.css(".product-sales-price ::text").getall()
            if t.strip() and t.strip() != "Standard Price"
        ]
        return ProductItem(
            brand="Ralph Lauren",
            product_id=tile.attrib.get("data-masterid"),
            item_id=tile.attrib.get("data-itemid"),
            name=tile.attrib.get("data-pname"),
            url=urljoin(
                str(self.response.url),
                tile.css("a.thumb-link::attr(href)").get() or "",
            ),
            image_url=self._image_url(tile),
            price_text=" ".join(price_parts),
            currency=self._currency(price_parts),
            stock=tile.attrib.get("data-stockmsg"),
            category=tile.attrib.get("data-cgid") or self._category_from_url,
            gender=tile.attrib.get("data-pagegender"),
            listing_url=str(self.response.url),
            total_in_category=total,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    @property
    def _category_from_url(self):
        """Fallback category: the listing URL slug, e.g.
        men-big-and-tall-casual-shirts (US tiles carry no data-cgid,
        unlike the PK/global storefront)."""
        slug = str(self.response.url).rstrip("/").split("/")[-1]
        return slug or None

    @property
    def total_in_category(self):
        """The "N Items" count shown on listing pages, if present."""
        text = self.response.text or ""
        for count in re.findall(r"(\d[\d,]*)\s+[Ii]tems?\b", text):
            try:
                if int(count.replace(",", "")) > 0:
                    return int(count.replace(",", ""))
            except ValueError:
                continue
        return None

    @staticmethod
    def _currency(price_parts):
        """Infer the currency code from the price text symbol ($ → USD)."""
        text = " ".join(price_parts)
        for symbol, code in CURRENCY_SYMBOLS:
            if symbol in text:
                return code
        return None

    @staticmethod
    def _image_url(tile):
        """Prefer an already-loaded srcset; fall back to the data-images
        attribute that lazy tiles carry."""
        srcset = tile.css("picture source::attr(srcset)").get()
        if srcset:
            # srcset is "url1 320w, url2 640w, ..." — keep the largest.
            return srcset.split(",")[-1].strip().split(" ")[0]
        data_images = tile.css("picture::attr(data-images)").get() or ""
        match = re.search(r"'desktop'\s*:\s*'([^']+)'", data_images)
        return match.group(1) if match else None
