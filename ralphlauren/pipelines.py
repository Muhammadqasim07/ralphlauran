"""Item pipelines for the ralphlauren project.

- ``ValidationPipeline`` drops malformed items and normalizes strings.
- ``DedupePipeline`` keeps one row per product across categories.

Enable them via ITEM_PIPELINES in settings.py.
"""

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem


class ValidationPipeline:
    """Drop items missing required fields; normalize whitespace in strings."""

    REQUIRED_FIELDS = ("product_id", "name", "url")

    def __init__(self, stats=None):
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.stats)

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        missing = [f for f in self.REQUIRED_FIELDS if not adapter.get(f)]
        if missing:
            self.stats.inc_value("items_dropped/missing_fields")
            raise DropItem(f"missing {missing}: {adapter.get('product_id')}")
        for field in adapter.field_names():
            if isinstance(adapter.get(field), str):
                adapter[field] = " ".join(adapter[field].split())
        return item


class DedupePipeline:
    """Keep the first row scraped per product_id, drop later duplicates.

    The same product shows up on many listing pages (parent categories,
    edits, featured rows). The first row wins — with Scrapy's breadth-first
    scheduling that is often a broad parent category, so run with
    ``-a include=men/clothing/casual-shirts`` when you need rows tied to a
    specific category branch.
    """

    def __init__(self, stats=None):
        self.stats = stats
        self.seen = set()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.stats)

    def process_item(self, item, spider):
        product_id = item["product_id"]
        if product_id in self.seen:
            self.stats.inc_value("items_dropped/duplicate")
            raise DropItem(f"duplicate product {product_id}")
        self.seen.add(product_id)
        return item
