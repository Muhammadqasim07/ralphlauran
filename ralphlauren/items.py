# Define here the models for your scraped items
#
# For documentation see:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class RalphlaurenItem(scrapy.Item):
    # define the fields for your item here.
    # name = scrapy.Field()
    pass


class ProductItem(scrapy.Item):
    brand = scrapy.Field()
    product_id = scrapy.Field()
    item_id = scrapy.Field()
    name = scrapy.Field()
    url = scrapy.Field()
    image_url = scrapy.Field()
    price_text = scrapy.Field()
    currency = scrapy.Field()
    stock = scrapy.Field()
    category = scrapy.Field()
    gender = scrapy.Field()
    listing_url = scrapy.Field()
    total_in_category = scrapy.Field()
    scraped_at = scrapy.Field()
