import scrapy


# class RalphlaurensSpider(scrapy.Spider):
#     name = "ralphlaurens"
#     allowed_domains = ["www.ralphlauren.com"]
#     start_urls = ["https://www.ralphlauren.global/pk/en/men/clothing/casual-shirts/10202?ab=EU_DLP_M_Slot_2_S1_Image1_SHOP"]
#
#     def parse(self, response):
#         pass

import scrapy


import scrapy


class TestZyteSpider(scrapy.Spider):
    name = "test_zyte"

    def start_requests(self):
        url = "https://www.ralphlauren.global/pk/en/men/clothing/casual-shirts/10202"

        yield scrapy.Request(
            url,
            meta={
                "zyte_api_automap": {
                    "browserHtml": True,
                }
            },
            callback=self.parse,
        )

    def parse(self, response):
        print("=" * 60)
        print("STATUS:", response.status)
        print("URL:", response.url)
        print("TITLE:", response.css("title::text").get())
        print("LENGTH:", len(response.text))
        print("=" * 60)

        yield {
            "status": response.status,
            "url": response.url,
            "title": response.css("title::text").get(),
        }
