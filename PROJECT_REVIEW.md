# Ralph Lauren Scraper — Project Review

*Last updated: 2026-10-02*

This document summarizes the current state of the project, the architecture,
what was changed and why, bugs found and fixed along the way, and what is
still open. Everything marked **verified** was tested against the live site
through Zyte API.

---

## 1. What this project does

| Spider | Storefront | Scope | Status |
|---|---|---|---|
| `rl_products` | `ralphlauren.global/pk/en` (PK) | All categories, PKR prices | working |
| `rl_us` | `ralphlauren.com` (US flagship) | All categories, **scoped to a US zip code**, USD prices | working, verified |
| `test_zyte` | — | leftover debug spider (no-op) | can be deleted |

Both spiders crawl **category listing pages** (product grids) with **full
pagination**: grids render 30 tiles server-side and further pages live at
`?page=N` on the same URL (verified live — the site ignores the classic SFCC
`start=`/`sz=` params, and `Search-Show` pipeline URLs are hard-banned with
520). The spider follows `?page=2, 3, …` until the site's "N Items" count is
reached, a page comes back short/empty, or `max_pages` (default 50) caps the
loop. Verified: US `men-big-and-tall-casual-shirts` → **41/41 products**;
PK `men/clothing/casual-shirts/10202` → **187 unique products** (site counter
says 188; the loop ran to the site's natural empty-page end and dropped
nothing — the off-by-one is a non-product tile the site counts).

**Single-category mode** — scrape every product of one category:

```bash
scrapy crawl rl_us -a zip_code=10001 -a category=men-big-and-tall-casual-shirts -o cat.jsonl
scrapy crawl rl_products -a category=10202 -o cat.jsonl        # PK, by id
```

They do **not** visit individual product detail pages.

---

## 2. Architecture

```
ralphlauren/
├── settings.py          # Zyte API key (env var), addons, session config
├── items.py             # ProductItem (one row per product)
├── pages.py             # PAGE OBJECTS — all parsing lives here
├── middlewares.py       # block-page retry + session health checker
├── pipelines.py         # validation + cross-category dedup
└── spiders/
    ├── rl_products.py   # PK storefront (CrawlSpider-style link following)
    └── rl_us.py         # US storefront, zip-code scoped, own session pool
```

### 2.1 Page objects (`pages.py`) — scrapy-poet + web-poet

All parsing for a category grid lives in `ListingPage(WebPage)`. The spider
never parses HTML itself — scrapy-poet injects the page object into the
callback based on the type annotation:

```python
def parse_listing(self, response, listing_page: ListingPage):
    yield from listing_page.to_items()
```

- Parsing is unit-testable offline (feed a saved HTML fixture — zero API cost).
- Works unchanged on **both** storefronts — the tile markup is identical
  (`div.product-tile` + `data-masterid` / `data-pname` / `product-sales-price`),
  verified on both.
- Currency is inferred from the price symbol (`$` → USD, `Rs` → PKR), not
  hardcoded.
- `image_url` returns a single URL (largest from the srcset), not the raw
  srcset blob.
- `category` falls back to the URL slug on the US site (US tiles carry no
  `data-cgid`).

### 2.2 Pipelines (`pipelines.py`)

1. **`ValidationPipeline` (100)** — drops items missing `product_id` / `name` /
   `url`, normalizes whitespace. Stats: `items_dropped/missing_fields`.
2. **`DedupePipeline` (200)** — one row per `product_id`; cross-category
   duplicates dropped (the same shirt appears on parent and child category
   pages). Stats: `items_dropped/duplicate`.

### 2.3 Middlewares (`middlewares.py`)

- **`BlockPageRetryMiddleware`** — some anti-bot pages arrive with HTTP 200,
  so it checks content markers ("Access Denied", "Pardon our interruption"…)
  plus 401/403/429 statuses, and retries up to 2 times before giving up.
- **`RalphlaurenSessionChecker`** — used by the scrapy-zyte-api session
  middleware on the PK spider: after each response it says whether the session
  is still healthy; unhealthy sessions are replaced automatically.

The Zyte API and scrapy-poet middlewares (download handler, sessions,
dependency injection) are installed automatically by their addons.

### 2.4 Zyte API setup (`settings.py`)

- API key read from the `ZYTE_API_KEY` environment variable — **never
  hardcoded** (see security note in §5).
- `ADDONS`: `scrapy_poet.Addon` (550) + `scrapy_zyte_api.Addon` (400).
- Every page needs browser rendering: the site returns 403 to plain HTTP from
  non-browser clients (verified with curl).
- Sessions (PK spider): `ZYTE_API_SESSION_ENABLED = True`, pool size 4,
  1s delay per session, init defaults to one browser request.

---

## 3. The US zip-code feature (`rl_us`)

### How to run

```bash
export ZYTE_API_KEY=...                       # your key
scrapy crawl rl_us -a zip_code=10001 -o products.jsonl

# limit to certain categories / cap spend while testing:
scrapy crawl rl_us -a zip_code=10001 -a include=casual-shirts -o shirts.jsonl
scrapy crawl rl_us -a zip_code=10001 -s CLOSESPIDER_PAGECOUNT=10
```

Arguments: `-a zip_code=` (required, 5 digits), `-a include=` (substring
filter on category URLs), `-a pool_size=` (default 4 zip-scoped sessions).

### How it works — verified step by step

When a user enters a zip on ralphlauren.com, the site calls its own endpoint:

```
POST /on/demandware.store/Sites-RalphLauren_US-Site/en_US/StoreInventory-SetZipCode
     body: zipCode=10001   (needs header X-Requested-With: XMLHttpRequest)
```

The spider replicates exactly that. Per session:

1. **Session is born as a browser request** to the homepage (browserHtml via
   Zyte API, US exit IPs via `geolocation: "us"`).
2. **The zip code is POSTed once** through the same session — a cheap
   plain-HTTP request. The site ties the zip to the session cookies; confirmed
   by `StoreInventory-GetZipCode` returning `[{"zip":"10001"}]`.
3. **All category pages are fetched with browserHtml through those
   zip-scoped sessions**, so listings are served for that delivery location —
   the same view a local shopper gets.

A pool of 4 such sessions spreads requests; failed/unconfirmed sessions are
skipped with a warning.

### Why `rl_us` manages its own sessions

Two Zyte API platform constraints discovered during testing:

- **Sessions must be born as browser requests.** A session created by a
  plain-HTTP request cannot later be used by a browserHtml request — Zyte API
  rejects it with `422 "Session has expired"`. (The zip POST must be plain
  HTTP because browser actions cannot POST forms.)
- The scrapy-zyte-api session middleware initializes a session with a single
  request, so it cannot express "browser init, *then* zip POST". `rl_us`
  therefore builds its own pool with raw `zyte_api` params and disables the
  session middleware via `custom_settings` — the PK spider still uses it.

### What the zip does and does not change

- ✅ Scopes the session to that delivery location (store availability /
  "find in store" context) — everything is served as for a shopper at that zip.
- ℹ️ US listing **prices are national**, so grid rows do not change zip-to-zip.
  The zip matters for store/inventory and delivery contexts.

---

## 4. Bugs found and fixed during this work

| # | Bug | Fix |
|---|---|---|
| 1 | **`start_requests()` is never called in Scrapy 2.19** — the engine only consumes `async def start()`. Both spiders silently fell back to the default `start()` (no callback), and the PK spider only worked by accident via the Zyte transparent-mode browser fallback. | Both spiders now define `async def start()`. |
| 2 | Session init with actions-only params → every session init failed with `422 "No data requested"` (8/8 failures in a test run). | Init params must include a data request (default `{"browserHtml": True}` is fine). Documented in settings.py. |
| 3 | Sessions born from plain-HTTP init die on browser reuse (`422 "Session has expired"`). | `rl_us` births every session with a browser request first. |
| 4 | SFCC JSON endpoints return plain (non-text) Scrapy responses — `response.text` raises `AttributeError`. | Read `response.body` and decode manually. |
| 5 | `image_url` contained the whole srcset blob (`url1 320w, url2 640w, …`). | Parse srcset, keep the largest URL. |
| 6 | Same product repeated across categories (parent/child grids). | `DedupePipeline` keeps one row per `product_id`. |
| 7 | Currency hardcoded `"PKR"`. | Inferred from the price symbol. |
| 8 | US tiles carry no `data-cgid` → empty `category`. | Fallback to the listing URL slug. |

Also fixed in review (first session): hardcoded Zyte API key removed from
settings (now env var), "1 Item" singular matched in the total-count regex.

---

## 5. Open items

1. **Rotate the Zyte API key.** The old key was hardcoded in settings.py and
   shared/exposed. It still works but should be considered compromised —
   rotate it in the Zyte dashboard and use the `ZYTE_API_KEY` env var.
2. `test_zyte` spider in `spiders/ralphlaurens.py` is dead debug code — safe
   to delete.
3. `zyte-common-items` is installed but unused (available if you later want
   the standardized Product schema).
4. `include=`-filtered runs of `rl_us` may schedule few categories — the
   filter matches on URL substring; prefer the exact `category=` argument for
   single categories.

---

## 6. Cost knobs (Zyte API billing)

- Every listing page (each grid page included) is a **browser request** (site
  403s plain HTTP). The zip POSTs are cheap plain-HTTP requests.
- A full category costs ~`ceil(N/30) + 1` browser requests (grid pages + the
  discovery request that found it).
- `rl_us` warmup costs ~`pool_size × 2` requests (browser homepage + zip POST
  per session) before the first listing — use `CLOSESPIDER_PAGECOUNT ≥ 12`
  in test runs so listings actually run (PK runs need extra budget for the
  session middleware's init requests: ~4 more).
- `-a category=...` / `-a include=...` limit categories; `-a max_pages=`
  caps grid pages per category; `CLOSESPIDER_PAGECOUNT` caps total pages;
  `pool_size` and `DOWNLOAD_DELAY` / session delay control pacing.

## 7. Environment

- Interpreter: shared venv at `/home/qasim/PycharmProjects/venv`
  (Scrapy 2.19, scrapy-zyte-api 0.36.x, scrapy-poet 0.27.x, web-poet,
  zyte-common-items). Note: the PyPI package is `scrapy-poet` — `scrapy-po`
  is an abandoned placeholder.
- Run from the project root (`scrapy.cfg` location).
