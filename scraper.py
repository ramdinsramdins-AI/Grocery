#!/usr/bin/env python3
"""Shelf Check scraper: collects NZ supermarket shelf prices and writes JSON.

Outputs (in ./docs/data, so GitHub Pages can serve them to the site):
  latest.json    every product seen on the last run, with per-100g / per-100ml / each unit price
  history.jsonl  one line each time a product's price changes (keeps the repo small)
  compare.json   products found at 2+ stores, grouped by a normalised match key

Usage:
  python scraper.py                      # scrape every enabled store in config.json
  python scraper.py --store newworld     # one store only
  python scraper.py --probe woolworths   # save one raw response to raw/ so you can check field names
  python scraper.py --fixture fixtures   # offline run from saved raw responses (used by the tests)

It identifies itself honestly, waits between requests, and stops on 403/429
instead of trying to get around the block.
"""
import argparse
import datetime as dt
import html
import json
import os
import pathlib
import random
import re
import sys
import time
import urllib.parse

import requests

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "docs" / "data"   # served by GitHub Pages next to docs/index.html
RAW = ROOT / "raw"              # probe output, not published
CONTACT = " ".join((os.environ.get("SCRAPER_CONTACT") or "").split()) or "no contact set"  # strips stray newlines from pasted secrets
UA = f"ShelfCheckBot/0.1 (personal price comparison; {CONTACT})"


# ---------------------------------------------------------------- size and unit price helpers

def parse_size(text):
    """'500g' -> (500, 'g'); '1.5kg' -> (1500, 'g'); '2L' -> (2000, 'ml'); '6 x 330ml' -> (1980, 'ml'); '12pk' -> (12, 'ea')."""
    if not text:
        return None
    t = text.lower().replace(",", "")
    m = re.search(r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(kg|g|ml|l|litre|liter)s?\b", t)
    if m:
        qty, n, u = int(m.group(1)), float(m.group(2)), m.group(3)
        base = _to_base(n, u)
        return (qty * base[0], base[1])
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l|litre|liter)s?\b", t)
    if m:
        return _to_base(float(m.group(1)), m.group(2))
    m = re.search(r"(\d+)\s*(pk|pack|ea|each|rolls?|bags?|eggs?|sheets?)\b", t)
    if m:
        return (float(m.group(1)), "ea")
    return None


def _to_base(n, u):
    if u == "kg":
        return (n * 1000, "g")
    if u in ("l", "litre", "liter"):
        return (n * 1000, "ml")
    return (n, u)


def unit_price_from_size(price, size_text):
    """Compute (value, basis) from the shelf price and the pack size. basis is '100g', '100ml' or 'ea'."""
    s = parse_size(size_text)
    if not s or not price:
        return None
    qty, unit = s
    if unit == "ea":
        return (round(price / qty, 4), "ea")
    return (round(price / qty * 100, 4), "100" + unit)


def unit_price_from_string(text):
    """Parse a store-supplied comparison such as '$16.48/L', '$1.50 per 100g' or '$90 /kg' into (value, basis)."""
    if not text:
        return None
    t = text.lower().replace(",", "")
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*(?:/|per)\s*(\d+)?\s*(kg|g|l|ml|ea|each)\b", t)
    if not m:
        return None
    value, per, unit = float(m.group(1)), int(m.group(2) or 1), m.group(3)
    if unit == "each":
        unit = "ea"
    if unit == "ea":
        return (round(value / per, 4), "ea")
    grams_or_ml = per * (1000 if unit in ("kg", "l") else 1)
    base = "100g" if unit in ("kg", "g") else "100ml"
    return (round(value / grams_or_ml * 100, 4), base)


def match_key(brand, name, size_text):
    """Loose cross-store key: lowercase words from brand + name + normalised size. Exact matching is a starting point, not a promise."""
    text = re.sub(r"\b\d+(\.\d+)?\s*(kg|g|ml|l|ltr|pk|pack|ea)\b", " ", f"{brand or ''} {name or ''}".lower())
    words = re.sub(r"[^a-z0-9 ]", " ", text).split()
    stop = {"the", "and", "of", "pack", "value", "fresh", "nz", "new", "zealand", "each", "ea", "pk", "block", "approx"}
    words = sorted({(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
                    for w in words if w not in stop})
    s = parse_size(size_text)
    size = f"{s[0]:g}{s[1]}" if s else "?"
    return " ".join(words) + "|" + size


def make_record(store, pid, name, brand, size_text, price, was=None, club=None,
                store_unit_text=None, category=None, url=None):
    up = unit_price_from_string(store_unit_text) or unit_price_from_size(price, size_text)
    return {
        "store": store,
        "id": str(pid),
        "name": name,
        "brand": brand,
        "size": size_text,
        "price": round(price, 2),
        "was": round(was, 2) if was else None,
        "club": round(club, 2) if club else None,
        "unit_price": up[0] if up else None,
        "unit_basis": up[1] if up else None,
        "on_special": bool(was and was > price),
        "category": category,
        "url": url,
        "match_key": match_key(brand, name, size_text),
    }


# ---------------------------------------------------------------- HTTP

class Blocked(Exception):
    pass


BUSY = (502, 503, 504)   # the shop's server is briefly down or overloaded (New Gum Sarn 503, 2026-10-18): wait and retry


def _request(session, method, url, delay, **kw):
    time.sleep(random.uniform(*delay))
    for attempt in (1, 2, 3):
        try:
            r = session.request(method, url, timeout=30 if attempt == 1 else 60, **kw)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as e:
            if attempt == 3:
                raise
            problem, wait = type(e).__name__, 10 * attempt
        else:
            if r.status_code not in BUSY or attempt == 3:
                break
            after = r.headers.get("Retry-After", "")
            problem, wait = str(r.status_code), max(10 * attempt, min(int(after), 120) if after.isdigit() else 0)
        print(f"  {problem} on {url[:90]}, waiting {wait}s and retrying", file=sys.stderr)
        time.sleep(wait)
    if r.status_code in (403, 429):
        raise Blocked(f"{r.status_code} from {url}")
    r.raise_for_status()
    return r


def polite_get(session, url, delay, **kw):
    return _request(session, "GET", url, delay, **kw)


def polite_post(session, url, delay, **kw):
    return _request(session, "POST", url, delay, **kw)


# ---------------------------------------------------------------- Woolworths NZ (formerly Countdown)
# Endpoint shape is based on how the public site loads its own product lists. Check it with --probe woolworths.

def woolworths_parse(payload, category=None):
    out = []
    items = ((payload.get("products") or {}).get("items")) or []
    for it in items:
        if it.get("type") not in (None, "Product"):
            continue
        price_info = it.get("price") or {}
        size = it.get("size") or {}
        price = price_info.get("salePrice") or price_info.get("originalPrice")
        if not price:
            continue
        was = price_info.get("originalPrice") if price_info.get("isSpecial") else None
        club = price if price_info.get("isClubPrice") else None
        cup = None
        if size.get("cupPrice") and size.get("cupMeasure"):
            cup = f"${size['cupPrice']}/{size['cupMeasure']}"
        out.append(make_record(
            "woolworths", it.get("sku"), it.get("name"), it.get("brand"),
            size.get("volumeSize"), float(price), was and float(was), club and float(club),
            cup, category, f"https://www.woolworths.co.nz/shop/productdetails?stockcode={it.get('sku')}"))
    return out


def scrape_woolworths(cfg, gcfg, session, probe=False):
    session.headers.update({"x-requested-with": "OverlayScrollbars"})
    results = []
    for dept in cfg["departments"]:
        for page in range(1, gcfg["max_pages_per_category"] + 1):
            url = ("https://www.woolworths.co.nz/api/v1/products?target=browse&inStockProductsOnly=false"
                   f"&size=48&page={page}&dasFilter=Department;;{dept};false")
            payload = polite_get(session, url, gcfg["delay_seconds"]).json()
            if probe:
                return payload
            recs = woolworths_parse(payload, dept)
            if not recs:
                if page == 1:
                    raw = ((payload.get("products") or {}).get("items")) or []
                    print(f"  woolworths {dept}: 0 usable products (API returned {len(raw)}; "
                          f"first item keys: {sorted(raw[0])[:12] if raw else 'n/a'}; "
                          f"payload keys: {sorted(payload)[:8]})", file=sys.stderr)
                break
            results += recs
            print(f"  woolworths {dept} page {page}: {len(recs)}", file=sys.stderr)
    return results


# Woolworths ignores requests from cloud servers such as GitHub's. The workaround is to collect its prices from a
# home browser with collect-woolworths.js and upload the result as woolworths.json in the repo's main folder.
MANUAL_WOOLWORTHS = ROOT / "woolworths.json"
MAX_MANUAL_AGE_DAYS = 7


def load_manual_woolworths():
    """Return (records, collected_at) from woolworths.json, or None when it is missing, unreadable or too old."""
    if not MANUAL_WOOLWORTHS.exists():
        return None
    try:
        payload = json.loads(MANUAL_WOOLWORTHS.read_text())
        at = payload["collected_at"]
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
    except Exception as e:
        print(f"  woolworths.json is not usable ({e!r}); ignoring it", file=sys.stderr)
        return None
    if age.days > MAX_MANUAL_AGE_DAYS:
        print(f"  woolworths.json is {age.days} days old (limit {MAX_MANUAL_AGE_DAYS}); ignoring it", file=sys.stderr)
        return None
    recs = woolworths_parse(payload, "uploaded")
    if not recs:
        print("  woolworths.json had no usable products; ignoring it", file=sys.stderr)
        return None
    return recs, at


# ---------------------------------------------------------------- Foodstuffs (New World and PAK'nSAVE share one platform)
# Prices in the API are in cents. Check field names with --probe newworld before trusting a full run.

def foodstuffs_parse(store, payload, category=None):
    out = []
    for p in payload.get("products", []) or []:
        sp = p.get("singlePrice") or {}
        cents = sp.get("price")
        if not cents:
            continue
        price = cents / 100
        comp = sp.get("comparativePrice") or {}
        cup = None
        if comp.get("pricePerUnit") and comp.get("unitQuantity"):
            cup = f"${comp['pricePerUnit'] / 100}/{comp['unitQuantity']}"
        was = club = None
        for promo in p.get("promotions") or []:
            reward = promo.get("rewardValue")
            if reward and reward < cents:
                if promo.get("cardDependencyFlag"):
                    club = reward / 100
                else:
                    was, price = price, reward / 100
        # loose produce comes as size "kg" (price per kg) or "ea" with no comparative price; derive one
        unit = str(p.get("displayName") or "").strip().lower()
        if not cup and unit in ("kg", "ea"):
            cup = f"${price}/{unit}"
        out.append(make_record(
            store, p.get("productId"), p.get("name"), p.get("brand"), p.get("displayName"),
            price, was, club, cup, category))
    return out


def _category_names(obj, depth=0):
    """Collect top-level category names from whatever tree the categories endpoint returns."""
    names = []
    if isinstance(obj, dict):
        if "name" in obj and depth <= 1:
            names.append(str(obj["name"]))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                names += _category_names(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            names += _category_names(v, depth)
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen[:300]


FOODSTUFFS_CAP = 1000   # the search never returns more than 1,000 hits for one query (totalHits stops at 1000)
FOODSTUFFS_LEVELS = 3   # category0NI > category1NI > category2NI


def _category_filter(path):
    """'Pantry > Herbs & Spices' -> category0NI:"Pantry" AND category1NI:"Herbs & Spices"."""
    names = [n.strip().replace('"', '\\"') for n in path.split(" > ")]
    return " AND ".join(f'category{i}NI:"{n}"' for i, n in enumerate(names))


def _subcategories(payload, level):
    """Category names one level down, from the search's own facet counts. They include names from a product's other
    category trees (a chips packet is under Pantry and Snacks), which only adds duplicates, so nothing is missed."""
    facets = (payload.get("algoliaSearchResult") or {}).get("facets") or {}
    return list(facets.get(f"category{level}NI") or {})


def scrape_foodstuffs(store, cfg, gcfg, session, probe=False):
    domain = {"newworld": "newworld.co.nz", "paknsave": "paknsave.co.nz"}[store]
    tok = polite_post(session, f"https://www.{domain}/api/user/get-current-user", gcfg["delay_seconds"]).json()
    token = tok.get("access_token") or tok.get("token")
    if not token:
        raise RuntimeError(f"no guest token in response; keys: {list(tok)}")
    session.headers.update({"Authorization": f"Bearer {token}"})
    base = f"https://api-prod.{domain}/v1/edge"
    try:
        r = session.get(f"{base}/store/{cfg['store_id']}/categories", timeout=30)
        if r.ok:
            names = _category_names(r.json())
            print(f"  {store} top-level category names on the site: {names or r.text[:600]}", file=sys.stderr)
            if probe:
                RAW.mkdir(parents=True, exist_ok=True)
                (RAW / f"{store}-categories.json").write_text(json.dumps(r.json(), indent=2))
    except Exception as e:
        print(f"  {store}: could not list categories ({e!r})", file=sys.stderr)
    results = []
    seen_ids = set()
    aliases = cfg.get("category_aliases", {})
    todo = list(cfg["categories"])
    while todo:
        cat = todo.pop(0)
        for page in range(0, gcfg["max_pages_per_category"]):
            body = {
                "algoliaQuery": {
                    "attributesToHighlight": [],
                    "attributesToRetrieve": ["productID", "Type", "sponsored", "category0NI"],
                    "facets": ["brand", "category1NI", "category2NI", "onPromotion", "productFacets"],
                    "filters": f'stores:{cfg["store_id"]} AND {_category_filter(cat)}',
                    "hitsPerPage": 50,
                    "page": page,
                },
                "storeId": cfg["store_id"],
                "hitsPerPage": 50,
                "page": page,
                "sortOrder": "NI_POPULARITY_ASC",
                "tobaccoQuery": False,
            }
            payload = polite_post(session, f"{base}/search/paginated/products", gcfg["delay_seconds"], json=body).json()
            if probe:
                return payload
            if page == 0 and (payload.get("totalHits") or 0) >= FOODSTUFFS_CAP:
                level = cat.count(" > ") + 1
                subs = _subcategories(payload, level) if level < FOODSTUFFS_LEVELS else []
                if subs:   # re-query each sub-category instead; they are processed next, de-duplicated as usual
                    print(f"  {store} {cat}: search stops at {FOODSTUFFS_CAP} results, "
                          f"splitting into {len(subs)} sub-categories", file=sys.stderr)
                    todo = [f"{cat} > {s}" for s in subs] + todo
                    break
                print(f"  {store} {cat}: search stops at {FOODSTUFFS_CAP} results and cannot be split further; "
                      f"some products will be missing", file=sys.stderr)
            recs = foodstuffs_parse(store, payload, cat.split(" > ")[0])
            if not recs:
                if page == 0:
                    raw = payload.get("products") or []
                    print(f"  {store} {cat}: 0 usable products (API returned {len(raw)}; "
                          f"first item keys: {sorted(raw[0])[:14] if raw else 'n/a'}; "
                          f"first singlePrice: {raw[0].get('singlePrice') if raw else None})", file=sys.stderr)
                    if not raw and aliases.get(cat):
                        todo = list(aliases[cat]) + todo
                        print(f"  {store}: trying alternative names for {cat}: {aliases[cat]}", file=sys.stderr)
                break
            fresh = [r for r in recs if (r["id"] not in seen_ids)]   # categories overlap, so keep each product once
            seen_ids.update(r["id"] for r in fresh)
            results += fresh
            print(f"  {store} {cat} page {page}: {len(recs)}", file=sys.stderr)
            if page + 1 >= (payload.get("totalPages") or page + 2):   # last page: skip the request for an empty one
                break
    return results


# ---------------------------------------------------------------- Shopify stores (New Gum Sarn)
# Shopify shops publish their catalogue as plain JSON at /products.json (250 per page). robots.txt for newgumsarn.co.nz
# blocks carts, checkout, filtered and sorted views, but not this feed. Check the shop's terms before publishing.
BULK_VARIANT = re.compile(r"carton|case|box|ctn|bulk|pallet|/\s*\d+|\bx\s*\d+", re.I)


def shopify_parse(store, base, payload, vendor_is_brand=True):
    out = []
    for p in payload.get("products", []):
        variants = [v for v in p.get("variants", []) if v.get("available", True)]
        single = [v for v in variants if not BULK_VARIANT.search(v.get("title") or "")]
        if not single:
            continue
        v = single[0]
        try:
            price = float(v.get("price"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        try:
            cmp_price = float(v.get("compare_at_price") or 0)
        except ValueError:
            cmp_price = 0
        title = p.get("title") or ""
        # size comes from the title (the grams field includes packaging); unit price is worked out from it
        brand = p.get("vendor") if vendor_is_brand else None   # some shops put their own name in "vendor"
        out.append(make_record(store, v.get("sku") or p.get("id"), title, brand, title, price,
                               cmp_price if cmp_price > price else None, None, None,
                               p.get("product_type"), f"{base}/products/{p.get('handle')}"))
    return out


def scrape_shopify(store, cfg, gcfg, session, probe=False):
    base = cfg["base_url"].rstrip("/")
    results = []
    for page in range(1, gcfg["max_pages_per_category"] + 1):
        r = polite_get(session, f"{base}/products.json", gcfg["delay_seconds"], params={"limit": 250, "page": page})
        payload = r.json()
        if probe:
            return payload
        recs = shopify_parse(store, base, payload, cfg.get("vendor_is_brand", True))
        raw = payload.get("products", [])
        print(f"  {store} page {page}: {len(raw)} listed, {len(recs)} usable", file=sys.stderr)
        results += recs
        if len(raw) < 250:
            break
    return results


# ---------------------------------------------------------------- WooCommerce stores (FromK)
# The WooCommerce Store API (/wp-json/wc/store/v1/products) is the public feed the shop's own pages use; prices are in
# cents. robots.txt for fromk.co.nz does not cover /wp-json and asks for a 2 s crawl delay (the delay here is 2 to 4 s).
# Names look like "[Brand] English name / [브랜드] Korean name – 4g*16pk".
WOO_NAME = re.compile(r"^\s*(?:\[(?P<brand>[^\]]+)\]\s*)?(?P<name>.*?)(?:\s+/\s+.*?)?(?:\s+[–-]\s+(?P<size>[^–]+))?\s*$")
EACH_TIMES_COUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\s*[*x×]\s*(\d+)\s*(?:pk|p|pcs|ea|bags?)?\b", re.I)


def woocommerce_parse(store, payload):
    out = []
    for p in payload:
        if not p.get("is_in_stock", True):
            continue
        pr = p.get("prices") or {}
        unit = 10 ** int(pr.get("currency_minor_unit") or 0)
        try:
            price, regular = int(pr["price"]) / unit, int(pr.get("regular_price") or 0) / unit
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0:
            continue
        raw = re.sub(r"^[^\[]{1,40}?\s[–-]\s(?=\[)", "", html.unescape(p.get("name") or ""))   # "Smart Saving – [Brand] ..."
        m = WOO_NAME.match(raw)
        name, brand, size = m.group("name").strip(), m.group("brand"), (m.group("size") or "").strip()
        size = EACH_TIMES_COUNT.sub(lambda s: f"{s.group(3)} x {s.group(1)}{s.group(2)}", size)   # 4g*16pk -> 16 x 4g
        path = urllib.parse.urlparse(p.get("permalink") or "").path.strip("/").split("/")
        top = path[1].replace("-", " ").title() if len(path) > 2 and path[0] == "shop" else ""
        leaf = ((p.get("categories") or [{}])[0]).get("name") or ""
        category = " > ".join(x for x in (top, html.unescape(leaf)) if x)
        out.append(make_record(store, p.get("sku") or p.get("id"), name, brand, size or name, price,
                               regular if regular > price else None, None, None, category, p.get("permalink")))
    return out


def scrape_woocommerce(store, cfg, gcfg, session, probe=False):
    base = cfg["base_url"].rstrip("/")
    results = []
    for page in range(1, 200):
        r = polite_get(session, f"{base}/wp-json/wc/store/v1/products", gcfg["delay_seconds"],
                       params={"per_page": 100, "page": page})
        payload = r.json()
        if probe:
            return payload
        recs = woocommerce_parse(store, payload)
        print(f"  {store} page {page}: {len(payload)} listed, {len(recs)} usable", file=sys.stderr)
        results += recs
        if page >= int(r.headers.get("X-WP-TotalPages") or page) or not payload:
            break
    return results


# ---------------------------------------------------------------- Magento stores (NJK)
# Magento's storefront GraphQL endpoint (POST /graphql) is what the shop's own pages call. robots.txt for njk.co.nz blocks
# page URLs with "?" and catalogue pages but not /graphql. The "Store" header picks the English store view.
MAGENTO_QUERY = """{ products(filter: {category_id: {eq: "%s"}}, pageSize: 100, currentPage: %d) {
  page_info { total_pages }
  items { sku name stock_status url_key categories { name }
    price_range { minimum_price { final_price { value } regular_price { value } } } } } }"""


def magento_parse(store, base, payload):
    out = []
    for p in ((payload.get("data") or {}).get("products") or {}).get("items") or []:
        if p.get("stock_status") != "IN_STOCK":
            continue
        mp = ((p.get("price_range") or {}).get("minimum_price") or {})
        price = ((mp.get("final_price") or {}).get("value")) or 0
        regular = ((mp.get("regular_price") or {}).get("value")) or 0
        if price <= 0:
            continue
        cats = [c.get("name") for c in p.get("categories") or [] if c.get("name")]
        size = EACH_TIMES_COUNT.sub(lambda s: f"{s.group(3)} x {s.group(1)}{s.group(2)}", p.get("name") or "")  # 600ml*12
        out.append(make_record(store, p.get("sku"), p.get("name"), None, size, price,
                               regular if regular > price else None, None, None, " > ".join(cats[:2]),
                               f"{base}/{urllib.parse.quote(p.get('url_key') or '')}.html"))
    return out


def scrape_magento(store, cfg, gcfg, session, probe=False):
    base = cfg["base_url"].rstrip("/")
    headers = {"Store": cfg.get("store_view", "default")}
    results = []
    for page in range(1, 200):
        r = polite_post(session, f"{base}/graphql", gcfg["delay_seconds"], headers=headers,
                        json={"query": MAGENTO_QUERY % (cfg.get("root_category", "2"), page)})
        payload = r.json()
        if probe:
            return payload
        if payload.get("errors"):
            raise RuntimeError(f"{store} GraphQL error: {payload['errors'][0].get('message')}")
        recs = magento_parse(store, base, payload)
        listed = ((payload.get("data") or {}).get("products") or {})
        print(f"  {store} page {page}: {len(listed.get('items') or [])} listed, {len(recs)} usable", file=sys.stderr)
        results += recs
        if page >= ((listed.get("page_info") or {}).get("total_pages") or page):
            break
    return results


# ---------------------------------------------------------------- output

def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default



# ---------------------------------------------------------------- cross-store matching
# Pass 1: identical match_key (brand + name words + size). Pass 2 (fuzzy): same pack size and same brand (or one brand
# plus product-line words, "mccain pub style" vs "McCain"), name words similar, and no difference in a "variant" word
# (light, organic, vanilla, ...) or a number. Multipack sizes and loose produce have their own, stricter rules (see
# _size_keys and _loose). Two products from the same store are never merged. When unsure it does not match: a wrong
# match shows the shopper a false price comparison.

NOISE = {"the", "and", "of", "with", "in", "for", "from", "a", "pack", "pk", "value", "fresh", "nz", "new", "zealand",
         "each", "ea", "block", "approx", "size", "per", "kg", "g", "ml", "l"}
BRAND_NOISE = {"co", "company", "ltd", "limited", "food", "brand"}   # extra brand words that say nothing about the product
VARIANT_WORDS = {
    "light", "lite", "zero", "diet", "max", "sugar", "free", "unsweetened", "sweetened", "organic", "barn", "cage",
    "range", "reduced", "low", "fat", "trim", "full", "standard", "mild", "tasty", "vintage", "extra", "salted",
    "unsalted", "vanilla", "chocolate", "strawberry", "caramel", "spicy", "hot", "medium",
    "large", "small", "mini", "jumbo", "gluten", "vegan", "lactose", "dairy", "decaf", "whole", "skim", "protein",
    "plus", "kid", "blue", "green", "yellow", "red", "gold", "silver", "purple", "pink", "black", "white", "wholemeal",
    "wholegrain", "multigrain", "brown", "rye", "seeded", "sourdough", "toast", "thick", "thin", "crunchy", "smooth",
    "chunky", "creamy", "soft", "firm", "sweet", "sour", "dark", "lemon", "lime", "orange", "apple", "berry",
    "mango", "coconut", "honey", "chilli", "garlic", "onion", "tomato", "bbq", "salt", "vinegar",
    "chicken", "beef", "lamb", "pork", "fish", "tuna", "salmon", "unscented", "sensitive", "ultra", "mega", "double",
    "triple", "half", "mixed", "assorted", "roast", "raw", "smoked", "plain", "natural", "greek", "no", "added",
    "oat", "almond", "soy", "rice", "lactofree", "mature", "tasty", "colby", "edam", "mozzarella", "parmesan",
}
DEFAULT_WORDS = {"original", "classic"}   # the plain variant, often left unsaid: may be missing on one side only
# Flavours and ingredients. One store often names one that the other leaves out ("Arepa The Brain" is blackcurrant), so
# only a flavour on each side that the other lacks blocks a match: raspberry vs watermelon hand wash.
FLAVOUR_WORDS = {
    "raspberry", "raspberrie", "blueberry", "blueberrie", "berrie", "cherry", "cherrie", "cranberry", "cranberrie",
    "boysenberry", "blackcurrant", "passionfruit", "peach", "pineapple", "banana", "grape", "watermelon", "kiwifruit",
    "feijoa", "apricot", "pear", "plum", "fig", "pomegranate", "mandarin", "grapefruit", "guava", "lychee", "rhubarb",
    "elderflower", "lavender", "rose", "mint", "peppermint", "spearmint", "menthol", "ginger", "cinnamon", "vanilla",
    "teriyaki", "satay", "curry", "pepper", "cheese", "bacon", "ham", "prawn", "mushroom", "basil", "sesame", "cocoa",
    "coffee", "mocha", "latte", "cappuccino", "espresso", "matcha", "chai", "turmeric", "hazelnut", "peanut", "cashew",
    "macadamia", "walnut", "pistachio", "toffee", "butterscotch", "cookie", "churro", "hokey", "jalapeno", "chipotle",
    "sriracha", "kimchi", "cumin", "paprika", "rosemary", "thyme", "parsley", "coriander", "dill", "chive", "corn",
    "sweetcorn", "pumpkin", "kumara", "beetroot", "spinach", "kale", "carrot", "potato", "cola", "lemonade",
}
_SIZE_IN_NAME = re.compile(r"\b\d+(?:\.\d+)?\s*(?:kg|g|ml|l|ltr|pk|pack|ea|each)\b|\b\d+\s*[x×]\s*\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b")


def _stem(w):
    if w.endswith("oes") and len(w) > 4:      # potatoes -> potato, tomatoes -> tomato
        return w[:-2]
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


_PLAIN = str.maketrans("éèêëàâäôöñüûçíï’‘", "eeeeaaaoonuucii''")   # Woolworths writes "nestlé", Foodstuffs "Nestle"


def _words(text):
    text = _SIZE_IN_NAME.sub(" ", str(text or "").lower().translate(_PLAIN).replace("'", ""))
    return re.sub(r"[^a-z0-9 ]", " ", text).split()


def _brand_words(brand):
    """Stemmed brand words without a leading 'the': "The Homegrown Juice Company" -> ['homegrown', 'juice', 'company']."""
    w = [_stem(x) for x in _words(brand)]
    return w[1:] if len(w) > 1 and w[0] == "the" else w


def _brand_key(brand):
    return "".join(_brand_words(brand))


def _size_key(rec):
    s = parse_size(rec.get("size")) or parse_size(rec.get("name"))
    return f"{s[0]:g}{s[1]}" if s else None


_MULTIPACK = re.compile(r"^\s*(\d+)\s*[x×]\s*\d", re.I)


def _size_keys(rec):
    """[(key, kind)]: the size key ('main') plus multipack alternatives. Woolworths says '8pack' where Foodstuffs says
    '8 x 73ml' ('count'), and often puts the weight only in the name: 'oxo beef stock cubes 71g', size '12pack'. That
    weight may be the whole pack ('total') or one item ('unit'); _alt_ok decides which other sizes each may meet."""
    main = _size_key(rec)
    if not main:
        return []
    keys = [(main, "main")]
    m = _MULTIPACK.search(rec.get("size") or "")
    s = parse_size(rec.get("size"))
    if m:
        keys.append((f"{int(m.group(1))}ea", "count"))
    elif s and s[1] == "ea":
        w = parse_size(rec.get("name"))
        if w and w[1] == "g":
            keys.append((f"{w[0]:g}g", "total"))
        if w and w[1] != "ea":   # a volume is always per item: 'vista sparkling water 330ml', size '8pack'
            keys.append((f"{w[0] * s[0]:g}{w[1]}", "unit"))
    return keys


def _alt_ok(kind, f_alt, f_main):
    """May f_alt's alternative size of this kind stand for f_main's main size?"""
    if kind in ("count", "loose"):
        return True
    if kind == "total":   # '160g' in the name of an '8pack' = a 160g pack, or 8 x 20g
        return f_main["multi"] in (None, f_alt["count"])
    return f_main["multi"] == f_alt["count"]   # 'unit': '24g' in the name of a '3pack' = 3 x 24g only


_PRODUCE = re.compile(r"\bfresh (?:fruit|vegetable|herb)\b")
PRODUCE_NOISE = {"fruit", "vegetable", "herb", "loose", "whole", "head", "yellow"}


def _loose(rec):
    """'kg' or 'ea' for fruit and vegetables sold loose (no pack size), else None."""
    if _size_key(rec):
        return None
    if rec.get("store") == "woolworths":
        produce = _PRODUCE.search(str(rec.get("name") or "").lower()) or str(rec.get("brand") or "").lower() == "fresh"
        unit = {"100g": "kg", "ea": "ea"}.get(rec.get("unit_basis"))
    else:
        produce = rec.get("category") == "Fruit & Vegetables"
        unit = str(rec.get("size") or "").strip().lower()
    return unit if produce and unit in ("kg", "ea") else None


def _features(rec, vocab):
    words = _words(rec.get("name"))
    bw = _brand_words(rec.get("brand"))
    loose = _loose(rec)
    if loose:   # bananas, lemons, broccoli: no pack size and no brand worth comparing, so match on the name alone
        key = f"loose-{loose}"
        return {"brand": "produce", "bwords": [], "tokens": {_stem(w) for w in words} - set(bw) - NOISE - PRODUCE_NOISE,
                "size": key, "sizes": [(key, "loose")], "count": None, "multi": None}
    if not bw:  # some stores put the brand only inside the name: use it when it is a brand seen elsewhere
        for n in (2, 1):
            cand = [_stem(w) for w in words[:n]]
            if len(words) > n and "".join(cand) in vocab:
                bw = cand
                break
    toks = {_stem(w) for w in words if w not in NOISE} - set(bw) - NOISE   # Woolworths names repeat the brand
    sizes = _size_keys(rec)
    s, m = parse_size(rec.get("size")), _MULTIPACK.search(rec.get("size") or "")
    return {"brand": "".join(bw), "bwords": bw, "tokens": toks, "size": sizes[0][0] if sizes else None, "sizes": sizes,
            "count": int(s[0]) if s and s[1] == "ea" else None, "multi": int(m.group(1)) if m else None}


def _split_compounds(x, y):
    """x with each word that y has as two words split up: 'meganut' vs 'mega nut', 'nutrigrain' vs 'nutri grain'."""
    out = set(x)
    for w in x - y:
        for i in range(2, len(w) - 1):
            if w[:i] in y and w[i:] in y:
                out = (out - {w}) | {w[:i], w[i:]}
                break
    return out


def _similarity(a, b):
    """0 when the two token sets must not be merged, else a score in (0, 1]."""
    ta, tb = a["tokens"], b["tokens"]
    if not ta or not tb:
        return 0.0
    ta, tb = _split_compounds(ta, tb), _split_compounds(tb, ta)
    diff = ta ^ tb
    if any(w in VARIANT_WORDS or w.isdigit() or w.startswith("spf") for w in diff):
        return 0.0
    for w in diff & DEFAULT_WORDS:   # "Original Sweet Chilli Sauce" = "Sweet Chilli Sauce", but not "Salsa Corn Chips"
        has, lacks = (ta, tb) if w in ta else (tb, ta)
        if not lacks <= has:
            return 0.0
    if (ta - tb) & FLAVOUR_WORDS and (tb - ta) & FLAVOUR_WORDS:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    if ta <= tb or tb <= ta:
        jac = max(jac, 0.6)
    return jac if jac >= 0.5 else 0.0


def group_records(rows):
    """Return {group_key: {store: record, '_m': 'exact'|'fuzzy'}} for every group found at 2 or more stores."""
    vocab = {_brand_key(r.get("brand")) for r in rows if len(_brand_key(r.get("brand"))) >= 3}
    clusters = {}          # key -> {store: rec}
    order = []
    for r in rows:
        k = r["match_key"]
        c = clusters.setdefault(k, {})
        if r["store"] in c:
            k = f"{k}#{len(clusters)}"          # a second product with the same key at one store stays separate
            c = clusters.setdefault(k, {})
        c[r["store"]] = r
        order.append(k)
    fuzzy_keys = set()
    blocks = {}
    for k, c in clusters.items():
        for store, rec in c.items():
            f = _features(rec, vocab)
            if f["brand"]:
                for size, kind in f["sizes"]:
                    blocks.setdefault((size, f["brand"]), []).append((k, store, f, kind))
    owner = {k: k for k in clusters}               # union-find over cluster keys

    def find(x):
        while owner[x] != x:
            owner[x] = owner[owner[x]]
            x = owner[x]
        return x

    pairs, alt_pairs, cands = [], [], {}

    def consider(a, b, fa=None):
        (k1, s1, f1, kind1), (k2, s2, f2, kind2) = a, b
        if s1 == s2 or k1 == k2 or (kind1 != "main" and kind2 != "main" and kind1 != "loose"):
            return
        if (kind1 != "main" and not _alt_ok(kind1, f1, f2)) or (kind2 != "main" and not _alt_ok(kind2, f2, f1)):
            return
        sim = _similarity(fa or f1, f2)
        if not sim:
            return
        for k, store, other in ((k1, s2, k2), (k2, s1, k1)):   # every candidate per product and other store
            c = cands.setdefault((k, store), {})
            c[other] = max(sim, c.get(other, 0))
        (pairs if kind1 == kind2 == "main" else alt_pairs).append((sim, k1, k2, s1, s2))

    for (size, brand), members in blocks.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                consider(members[i], members[j])
        # Brand prefix: Woolworths' brand often carries the product line ("mccain pub style", "mrs rogers eco pack").
        # When one brand is the other plus whole extra words, those extra words count as name words.
        for a in members:
            bw = a[2]["bwords"]
            for n in range(1, len(bw)):
                short = "".join(bw[:n])
                if len(short) < 3 or (size, short) not in blocks:
                    continue
                fa = dict(a[2], tokens=a[2]["tokens"] | (set(bw[n:]) - BRAND_NOISE - NOISE))
                for b in blocks[(size, short)]:
                    consider(a, b, fa)

    def clear_best(k, store, other, sim):
        return all(o == other or s < sim - 0.1 for o, s in cands[(k, store)].items())

    # A multipack alternative size or a loose-produce pair is only trusted when each product is the other's clear best
    # match at that store (a '6pack' must not pick between '6 x 250ml' and '6 x 330ml', nor 'apples' between varieties).
    pairs += [p for p in alt_pairs if clear_best(p[1], p[4], p[2], p[0]) and clear_best(p[2], p[3], p[1], p[0])]
    for sim, k1, k2, _, _ in sorted(pairs, reverse=True):   # best pairs first, so a weaker pair cannot take a store's slot
        a, b = find(k1), find(k2)
        if a == b or set(clusters[a]) & set(clusters[b]):
            continue
        clusters[a].update(clusters[b])
        del clusters[b]
        owner[b] = a
        fuzzy_keys.add(a)
    out = {}
    for k, c in clusters.items():
        if len(c) >= 2:
            g = dict(c)
            g["_m"] = "fuzzy" if k in fuzzy_keys else "exact"
            out[k] = g
    return out


def match_report(top=15):
    """Print how well products line up. Run: python scraper.py --match-report  (after a scrape)."""
    data = load_json(DATA / "latest.json", {"products": []})
    rows = data.get("products", [])
    groups = group_records(rows)
    by_store = {}
    for r in rows:
        by_store[r["store"]] = by_store.get(r["store"], 0) + 1
    matched = {(s, g[s]["id"]) for g in groups.values() for s in g if s != "_m"}
    print("products per store:", by_store)
    print(f"groups: {len(groups)} ({sum(1 for g in groups.values() if g['_m'] == 'exact')} exact, "
          f"{sum(1 for g in groups.values() if g['_m'] == 'fuzzy')} fuzzy)")
    for s, n in by_store.items():
        m = sum(1 for r in rows if r["store"] == s and (s, r["id"]) in matched)
        print(f"  {s}: {m} of {n} matched ({100 * m // max(n, 1)}%)")
    print("\nsample fuzzy matches (check these are the same product):")
    shown = 0
    for k, g in groups.items():
        if g["_m"] == "fuzzy" and shown < top:
            print("  " + "  <->  ".join(f"[{s}] {g[s].get('brand') or ''} {g[s]['name']} {g[s].get('size') or ''}" for s in g if s != "_m"))
            shown += 1
    print("\nsample unmatched products, with the closest other-store product of the same size:")
    vocab = {_brand_key(r.get("brand")) for r in rows if len(_brand_key(r.get("brand"))) >= 3}
    feats = {(r["store"], r["id"]): _features(r, vocab) for r in rows}
    unmatched = [r for r in rows if (r["store"], r["id"]) not in matched and feats[(r["store"], r["id"])]["size"]]
    random.Random(1).shuffle(unmatched)
    for r in unmatched[:top]:
        f = feats[(r["store"], r["id"])]
        best = None
        for o in rows:
            if o["store"] == r["store"]:
                continue
            fo = feats[(o["store"], o["id"])]
            if fo["size"] == f["size"] and f["tokens"] and fo["tokens"]:
                j = len(f["tokens"] & fo["tokens"]) / len(f["tokens"] | fo["tokens"])
                if best is None or j > best[0]:
                    best = (j, o)
        near = f"closest: [{best[1]['store']}] {best[1].get('brand') or ''} {best[1]['name']} (brand key {feats[(best[1]['store'], best[1]['id'])]['brand'] or '-'}, overlap {best[0]:.2f})" if best else "no same-size product elsewhere"
        print(f"  [{r['store']}] {r.get('brand') or ''} {r['name']} {r.get('size') or ''} (brand key {f['brand'] or '-'}) -> {near}")


# ---------------------------------------------------------------- recipe ingredients -> products
# ingredients.json (repo root) says which supermarket products count as "chicken breast", "plain flour", and so on.
# The scraper writes docs/data/ingredient_products.json: for each ingredient and store, the pack sizes on sale, which the
# recipe page uses to work out the cheapest packs that cover what the chosen recipes need.
INGREDIENTS = ROOT / "ingredients.json"
MAX_PACKS_PER_STORE = 6
WEIGHT_RANGE = re.compile(r"\d\s*(?:kg|g)?\s*-\s*\d+(?:\.\d+)?\s*(?:kg|g)\b")


# Store aisles that never hold a cooking ingredient (Foodstuffs top-level names; New Gum Sarn, TXG Mall, NJK and
# FromK categories, which for NJK and FromK read "Top > Leaf").
NOT_FOOD_AISLE = re.compile(r"^(pets|baby & toddler|health & body|household & cleaning|homewares|beer, wine & cider)$"
                            r"|soap|dental|cough|massage|remed|insecticide|stomach|laundry|liner|cleaning|candle|incense"
                            r"|everyday essentials|mum & baby|baby & kids|personal care|cosmetic|beauty|household"
                            r"|kitchenware|daily necessities|medicine", re.I)
# Words that mark a product as something made from the ingredient, or not food at all. Applies to every ingredient
# except where the ingredient's own include rule asks for the word (noodles may say "noodle", soy sauce "sauce").
NOT_INGREDIENT = [
    "sunscreen", "razor", "blade", "liner", "pod", "lozenge", "supplement", "tablet", "capsule", "vitamin", "shampoo",
    "conditioner", "lotion", "moisturiser", "deodorant", "wipe", "detergent", "dishwasher", "cleaner", "beauty",
    "bb cream", "day cream", "shave", "cat food", "dog food", "puppy", "kitten", "months", "kindy", "baby food",
    "pizza", "pie", "quiche", "tortellini", "tortelloni", "ravioli", "risotto", "lasagne", "soup", "chowder", "meal",
    "hummus", "dip", "chip", "crisp", "cracker", "biscuit", "pretzel", "popcorn", "chocolate", "donut", "muffin",
    "cake", "kombucha", "drink", "smoothie", "shake", "cordial", "syrup", "lolly", "lollies", "candy",
    "bar", "popper", "falafel", "focaccia", "wrap", "bun", "sauce", "paste", "powder", "seasoning", "stock", "cube",
    "spread", "pate", "dressing", "mayo", "mayonnaise", "fries", "relish", "chutney", "jam", "pickle", "pickled", "salsa", "pesto",
    "marinade", "gravy", "flavour", "flavoured", "mix", "kit", "sachet", "instant", "snack", "cereal", "muesli",
    "granola", "sushi", "yoghurt", "yogurt", "milk", "evaporated", "stix", "stick", "cone",
]
# New Gum Sarn's "Vegetables" and "Fruit" are canned and frozen goods; TXG Mall's are fresh
FRESH_AISLE = {"fruit & vegetables", "txgmall:vegetables", "txgmall:fruits"}
WOOLWORTHS_FRESH = re.compile(r"\bfresh (?:fruit|vegetable|herb|salad)\b|^(?:fresh|the odd bunch|the fresh grower)$")


def _has_term(term, words, text):
    t = term.lower().replace("'", "")
    return (t in text) if " " in t else (_stem(t) in words)


def _in_fresh_aisle(rec):
    cat = str(rec.get("category") or "").lower()
    if cat and cat not in ("uploaded", "fixture"):
        return cat in FRESH_AISLE or f"{rec.get('store')}:{cat}" in FRESH_AISLE
    # Woolworths data has no aisle, but its produce is branded "fresh vegetable", "fresh fruit" and so on
    return bool(WOOLWORTHS_FRESH.search(str(rec.get("name") or "").lower())
                or WOOLWORTHS_FRESH.search(str(rec.get("brand") or "").lower()))


def _ingredient_match(rec, spec):
    if NOT_FOOD_AISLE.search(str(rec.get("category") or "")):
        return False
    if spec.get("fresh") and not _in_fresh_aisle(rec):
        return False
    words = {_stem(w) for w in _words(f"{rec.get('name') or ''} {rec.get('brand') or ''}")}
    text = " ".join(_words(f"{rec.get('name') or ''} {rec.get('brand') or ''}"))
    # an ingredient's own words ("sauce" in fish sauce) and its "allow" list are exempt from the shared list
    asked = {_stem(w) for group in spec.get("include", []) for t in group for w in t.lower().split()}
    shared = [x for x in NOT_INGREDIENT if _stem(x) not in asked and x not in spec.get("allow", [])]
    if any(_has_term(x, words, text) for x in spec.get("exclude", []) + shared):
        return False
    return all(any(_has_term(alt, words, text) for alt in group) for group in spec.get("include", []))


def _ingredient_pack(rec, spec):
    """(amount in the ingredient's base unit, loose?) for one product, or None when it cannot be used."""
    base = spec["base"]
    each = None if spec.get("by_weight") else (spec.get("units") or {}).get("each")
    basis, up = rec.get("unit_basis"), rec.get("unit_price")
    size_text = str(rec.get("size") or "").lower()
    # Woolworths by-weight items ("min order 850g", "0.35-0.6kg 5-8pc", "580g - 800g"): the price is per kg
    if "min order" in size_text or WEIGHT_RANGE.search(size_text):
        return (100, True) if base in ("g", "ml") and basis == "100" + base and up else None
    size = parse_size(rec.get("size")) or parse_size(rec.get("name"))
    if size:
        qty, unit = size
        if unit == base:
            return (qty, False)
        if spec.get("g_or_ml") and {unit, base} == {"g", "ml"}:   # sauces are sold by weight or by volume; close enough
            return (qty, False)
        if unit == "ea" and base in ("g", "ml") and each:
            return (qty * each, False)
        return None
    if base in ("g", "ml") and basis == "100" + base and up:
        return (100, True)                      # sold loose by weight: priced per 100 g, any amount can be bought
    text = f"{rec.get('size') or ''} {rec.get('name') or ''}".lower()
    if basis == "ea" or re.search(r"\b(each|ea)\b", text):
        if base == "ea":
            return (1, False)
        if base == "g" and each:
            return (each, False)
    return None


def _display_name(rec):
    name = str(rec.get("name") or "").strip()
    brand = str(rec.get("brand") or "").strip()
    if brand and brand.lower() not in name.lower():
        name = f"{brand} {name}"
    size = str(rec.get("size") or "").strip()
    if size and size.lower() not in name.lower():
        name = f"{name} {size}"
    return name


def ingredient_candidates(rows, spec):
    """{store: [pack, ...]} for one ingredient. A pack is {n, q, p, c, w, u, l}: name, amount, price, club, was, url, loose."""
    by_store = {}
    for r in rows:
        if not _ingredient_match(r, spec):
            continue
        pack = _ingredient_pack(r, spec)
        if not pack or pack[0] <= 0:
            continue
        qty, loose = pack
        price = r["unit_price"] if loose else r["price"]
        club = None if loose else r.get("club")
        was = None if loose else r.get("was")
        c = {"n": _display_name(r), "q": qty, "p": round(price, 4 if loose else 2), "c": club, "w": was, "u": r.get("url"), "l": 1 if loose else 0}
        mo = re.search(r"min order\s*(.+)", str(r.get("size") or ""), re.I) if loose else None
        least = parse_size(mo.group(1)) if mo else None
        if least and least[1] == spec["base"]:
            c["m"] = least[0]                    # Woolworths "min order 1.8kg": by weight, but at least this much
        by_store.setdefault(r["store"], []).append(c)
    out = {}
    for store, packs in by_store.items():
        per = lambda c: c["p"] / (100 if c["l"] else c["q"])
        if len(packs) >= 3:                      # drop products priced far from the typical one: usually a wrong match
            costs = sorted(per(c) for c in packs)
            med = costs[len(costs) // 2]
            # the low bound is loose: raw produce sold by weight is often a fifth of the price of the cut, snack-size packs
            packs = [c for c in packs if 0.15 * med <= per(c) <= 3 * med]
        loose = sorted((c for c in packs if c["l"]), key=lambda c: c["p"])
        loose_best = loose[:1]
        if loose and loose[0].get("m"):          # cheapest has a minimum order: also keep the cheapest that has none
            loose_best += [c for c in loose if not c.get("m")][:1]
        cheapest = {}
        for c in packs:
            if not c["l"] and (c["q"] not in cheapest or c["p"] < cheapest[c["q"]]["p"]):
                cheapest[c["q"]] = c
        kept = sorted(cheapest.values(), key=per)[:MAX_PACKS_PER_STORE]
        if cheapest:
            smallest = cheapest[min(cheapest)]
            if smallest not in kept:
                kept.append(smallest)
        out[store] = loose_best + sorted(kept, key=lambda c: c["q"])
    return out


def build_ingredient_products(rows, now, store_times=None):
    cat = load_json(INGREDIENTS, None)
    if not cat:
        return None
    ings = {}
    for iid, spec in cat["ingredients"].items():
        ings[iid] = {"name": spec["name"], "base": spec["base"], "pantry": spec.get("pantry", False),
                     "perishable": spec.get("perishable", False), "units": spec.get("units", {}),
                     "stores": ingredient_candidates(rows, spec)}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "ingredient_products.json").write_text(json.dumps({"generated_at": now, "store_times": store_times or {}, "ingredients": ings}, separators=(",", ":")))
    return ings


def ingredient_report():
    """Print, for every recipe ingredient, what the scraper picked at each store. Run: python scraper.py --ingredient-report"""
    data = load_json(DATA / "latest.json", {"products": []})
    ings = build_ingredient_products(data.get("products", []), data.get("generated_at", ""))
    if ings is None:
        print("ingredients.json not found")
        return
    for iid, v in ings.items():
        print(f"\n{v['name']} ({iid}, base {v['base']})")
        if not v["stores"]:
            print("  NO PRODUCTS FOUND at any store: check the rules in ingredients.json")
        for store, packs in v["stores"].items():
            print(f"  {store}: " + "; ".join(f"{c['n']} = ${c['p']:.2f}" + (" per 100" if c["l"] else f" for {c['q']:g}") for c in packs))


def write_outputs(records, now, store_times=None):
    DATA.mkdir(parents=True, exist_ok=True)
    prev = load_json(DATA / "latest.json", {"products": []})
    if prev.get("generated_at") == "sample":  # the demo data shipped with the site is replaced, never kept
        prev = {"products": []}
    prev_by_key = {(p["store"], p["id"]): p for p in prev.get("products", [])}

    changes = []
    for r in records:
        old = prev_by_key.get((r["store"], r["id"]))
        if old is None or (old["price"], old.get("was"), old.get("club")) != (r["price"], r["was"], r["club"]):
            changes.append({"t": now, "store": r["store"], "id": r["id"], "price": r["price"],
                            "was": r["was"], "club": r["club"]})
    if changes:
        with open(DATA / "history.jsonl", "a") as f:
            for c in changes:
                f.write(json.dumps(c) + "\n")

    # keep last-known rows for stores that failed this run, so one blocked store does not wipe its data
    scraped_stores = {r["store"] for r in records}
    kept = [p for p in prev.get("products", []) if p["store"] not in scraped_stores]
    all_rows = kept + records
    (DATA / "latest.json").write_text(json.dumps({
        "generated_at": now,
        "stores_scraped_this_run": sorted(scraped_stores),
        "products": all_rows}, separators=(",", ":")))

    compare = group_records(all_rows)
    print(f"  matching: {sum(1 for g in compare.values() if g['_m'] == 'exact')} exact groups, "
          f"{sum(1 for g in compare.values() if g['_m'] == 'fuzzy')} fuzzy groups", file=sys.stderr)
    (DATA / "compare.json").write_text(json.dumps({"generated_at": now, "stores_scraped_this_run": sorted(scraped_stores),
                    "store_times": store_times or {}, "groups": compare}, separators=(",", ":")))
    try:
        ings = build_ingredient_products(all_rows, now, store_times)
        if ings is not None:
            found = sum(1 for v in ings.values() if v["stores"])
            print(f"  recipe ingredients: products found for {found} of {len(ings)}", file=sys.stderr)
    except Exception as e:   # recipes are optional: never lose the price data because of them
        print(f"  recipe ingredient step failed: {e!r}", file=sys.stderr)
    return len(all_rows), len(changes), len(compare)


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=list(cfg["stores"]))
    ap.add_argument("--probe", choices=list(cfg["stores"]))
    ap.add_argument("--category", help='with --probe newworld/paknsave: the category to fetch, e.g. "Pantry" or "Pantry > Herbs & Spices"')
    ap.add_argument("--match-report", action="store_true", help="show how well products match across stores, from the last scrape")
    ap.add_argument("--ingredient-report", action="store_true", help="show which products were picked for each recipe ingredient")
    ap.add_argument("--fixture", help="directory of saved raw responses (<store>.json) for an offline run")
    args = ap.parse_args()

    if args.match_report:
        match_report()
        return
    if args.ingredient_report:
        ingredient_report()
        return

    gcfg = {k: cfg[k] for k in ("max_pages_per_category", "delay_seconds")}
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    if args.fixture:
        recs = []
        fx = pathlib.Path(args.fixture)
        if (fx / "woolworths.json").exists():
            recs += woolworths_parse(json.loads((fx / "woolworths.json").read_text()), "fixture")
        for s in ("newworld", "paknsave"):
            if (fx / f"{s}.json").exists():
                recs += foodstuffs_parse(s, json.loads((fx / f"{s}.json").read_text()), "fixture")
        print(write_outputs(recs, now))
        return

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    store_times = {}

    def run(store, probe=False):
        c = cfg["stores"][store]
        if probe and args.category:
            c = dict(c, categories=[args.category])
        if store == "woolworths":
            if not probe:
                manual = load_manual_woolworths()
                if manual:
                    store_times["woolworths"] = manual[1]
                    print(f"  woolworths: using uploaded woolworths.json from {manual[1]} ({len(manual[0])} products)", file=sys.stderr)
                    return manual[0]
            return scrape_woolworths(c, gcfg, session, probe)
        platform = {"shopify": scrape_shopify, "woocommerce": scrape_woocommerce, "magento": scrape_magento}
        if c.get("platform") in platform:
            return platform[c["platform"]](store, c, gcfg, session, probe)
        return scrape_foodstuffs(store, c, gcfg, session, probe)

    if args.probe:
        raw = run(args.probe, probe=True)
        RAW.mkdir(parents=True, exist_ok=True)
        out = RAW / f"{args.probe}.json"
        out.write_text(json.dumps(raw, indent=2))
        print(f"saved {out}. Open it and confirm the price, size and unit price fields match the parser.")
        return

    stores = [args.store] if args.store else [s for s, c in cfg["stores"].items() if c.get("enabled")]
    records, failed = [], []
    for s in stores:
        try:
            print(f"scraping {s}", file=sys.stderr)
            records += run(s)
        except Blocked as e:
            print(f"{s}: blocked ({e}). Stopping this store; not retrying.", file=sys.stderr)
            failed.append(s)
        except Exception as e:  # keep the other stores going
            print(f"{s}: failed ({e!r})", file=sys.stderr)
            failed.append(s)
    if not records:
        print("nothing scraped; leaving data untouched", file=sys.stderr)
        sys.exit(1)
    print(write_outputs(records, now, store_times))
    if failed:
        print(f"failed stores: {failed}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
