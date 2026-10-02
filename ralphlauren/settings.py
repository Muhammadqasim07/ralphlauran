"""Scrapy settings for the ralphlauren project.

Stack:
- Zyte API (scrapy-zyte-api addon): browser-rendered downloads + sessions
- scrapy-poet: page-object dependency injection (see ralphlauren/pages.py)
- custom middleware & pipelines: ralphlauren.middlewares / .pipelines
"""

import os

BOT_NAME = "ralphlauren"

SPIDER_MODULES = ["ralphlauren.spiders"]
NEWSPIDER_MODULE = "ralphlauren.spiders"

# ----------------------------------------------------------------- Zyte API
# Read the key from the environment — never hardcode it here. The
# scrapy-zyte-api addon also checks the ZYTE_API_KEY env var itself.
ZYTE_API_KEY = os.environ.get("ZYTE_API_KEY")

ADDONS = {
    # scrapy-poet >= 0.26 ships its own addon; the Zyte addon detects it
    # and relies on it to install InjectionMiddleware + providers.
    "scrapy_poet.Addon": 550,
    # Download handler, Zyte API middlewares (incl. session middlewares).
    "scrapy_zyte_api.Addon": 400,
}

# ----------------------------------------------------------------- Sessions
# Zyte API sessions pin an IP address + cookie jar per pool of requests,
# so the site sees a handful of consistent returning "browsers" instead
# of a brand-new identity on every request.
ZYTE_API_SESSION_ENABLED = True
# Session init parameters default to {"browserHtml": True}: one browser
# request to the target URL, giving each session a real browser handshake
# and its cookies. Only override ZYTE_API_SESSION_PARAMS if init needs
# extra work — and if you do, keep some data request in there
# (browserHtml/httpResponseBody), or the API rejects the init with 422
# "No data requested". Note: sessions born from plain-HTTP init requests
# cannot be reused by browserHtml requests (422 "Session has expired") —
# which is why the rl_us spider manages its own browser-born sessions
# and disables this middleware via its custom_settings.
# How many parallel sessions (distinct identities) to maintain per pool.
ZYTE_API_SESSION_POOL_SIZE = 4
# Delay between requests sharing a session (defaults to DOWNLOAD_DELAY).
ZYTE_API_SESSION_DELAY = 1.0
# RalphlaurenSessionChecker.check() decides after each response whether a
# session is still healthy; unhealthy sessions are replaced automatically.
ZYTE_API_SESSION_CHECKER = "ralphlauren.middlewares.RalphlaurenSessionChecker"

# ------------------------------------------------- Middleware and pipelines
DOWNLOADER_MIDDLEWARES = {
    # Detects soft blocks (block page served with HTTP 200) and retries.
    "ralphlauren.middlewares.BlockPageRetryMiddleware": 620,
}

ITEM_PIPELINES = {
    "ralphlauren.pipelines.ValidationPipeline": 100,
    "ralphlauren.pipelines.DedupePipeline": 200,
}

# ------------------------------------------------------------- Crawl policy
ROBOTSTXT_OBEY = False
DOWNLOAD_DELAY = 1.0

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
