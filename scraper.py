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
import json
import os
import pathlib
import random
import re
import sys
import time

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


def _request(session, method, url, delay, **kw):
    time.sleep(random.uniform(*delay))
    for attempt in (1, 2, 3):
        try:
            r = session.request(method, url, timeout=30 if attempt == 1 else 60, **kw)
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as e:
            if attempt == 3:
                raise
            wait = 10 * attempt
            print(f"  {type(e).__name__} on {url[:90]}, waiting {wait}s and retrying", file=sys.stderr)
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
                    "facets": ["brand", "category2NI", "onPromotion", "productFacets"],
                    "filters": f'stores:{cfg["store_id"]} AND category0NI:"{cat}"',
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
            recs = foodstuffs_parse(store, payload, cat)
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
    return results


# ---------------------------------------------------------------- Shopify stores (New Gum Sarn)
# Shopify shops publish their catalogue as plain JSON at /products.json (250 per page). robots.txt for newgumsarn.co.nz
# blocks carts, checkout, filtered and sorted views, but not this feed. Check the shop's terms before publishing.
BULK_VARIANT = re.compile(r"carton|case|box|ctn|bulk|pallet|/\s*\d+|\bx\s*\d+", re.I)


def shopify_parse(store, base, payload):
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
        out.append(make_record(store, v.get("sku") or p.get("id"), title, p.get("vendor"), title, price,
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
        recs = shopify_parse(store, base, payload)
        raw = payload.get("products", [])
        print(f"  {store} page {page}: {len(raw)} listed, {len(recs)} usable", file=sys.stderr)
        results += recs
        if len(raw) < 250:
            break
    return results


# ---------------------------------------------------------------- output

def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default



# ---------------------------------------------------------------- cross-store matching
# Pass 1: identical match_key (brand + name words + size). Pass 2 (fuzzy): same pack size and same brand, name words
# similar, and no difference in a "variant" word (light, organic, vanilla, ...) or a number. Two products from the same
# store are never merged. When unsure it does not match: a wrong match shows the shopper a false price comparison.

NOISE = {"the", "and", "of", "with", "in", "for", "from", "a", "pack", "pk", "value", "fresh", "nz", "new", "zealand",
         "each", "ea", "block", "approx", "size", "per", "kg", "g", "ml", "l"}
VARIANT_WORDS = {
    "light", "lite", "zero", "diet", "max", "sugar", "free", "unsweetened", "sweetened", "organic", "barn", "cage",
    "range", "reduced", "low", "fat", "trim", "full", "standard", "mild", "tasty", "vintage", "extra", "salted",
    "unsalted", "vanilla", "chocolate", "strawberry", "caramel", "original", "classic", "spicy", "hot", "medium",
    "large", "small", "mini", "jumbo", "gluten", "vegan", "lactose", "dairy", "decaf", "whole", "skim", "protein",
    "plus", "kid", "blue", "green", "yellow", "red", "gold", "silver", "purple", "pink", "black", "white", "wholemeal",
    "wholegrain", "multigrain", "brown", "rye", "seeded", "sourdough", "toast", "thick", "thin", "crunchy", "smooth",
    "chunky", "creamy", "soft", "firm", "sweet", "sour", "dark", "lemon", "lime", "orange", "apple", "berry",
    "mango", "coconut", "honey", "chilli", "garlic", "onion", "tomato", "bbq", "salt", "vinegar",
    "chicken", "beef", "lamb", "pork", "fish", "tuna", "salmon", "unscented", "sensitive", "ultra", "mega", "double",
    "triple", "half", "mixed", "assorted", "roast", "raw", "smoked", "plain", "natural", "greek", "no", "added",
    "oat", "almond", "soy", "rice", "lactofree", "mature", "tasty", "colby", "edam", "mozzarella", "parmesan",
}
_SIZE_IN_NAME = re.compile(r"\b\d+(?:\.\d+)?\s*(?:kg|g|ml|l|ltr|pk|pack|ea|each)\b|\b\d+\s*[x×]\s*\d+(?:\.\d+)?\s*(?:kg|g|ml|l)\b")


def _stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _words(text):
    text = _SIZE_IN_NAME.sub(" ", str(text or "").lower().replace("'", ""))
    return re.sub(r"[^a-z0-9 ]", " ", text).split()


def _brand_key(brand):
    return re.sub(r"[^a-z0-9]", "", str(brand or "").lower().replace("'", ""))


def _size_key(rec):
    s = parse_size(rec.get("size")) or parse_size(rec.get("name"))
    return f"{s[0]:g}{s[1]}" if s else None


def _features(rec, vocab):
    words = _words(rec.get("name"))
    brand = _brand_key(rec.get("brand"))
    drop = {_stem(w) for w in _words(rec.get("brand"))}
    if not brand:  # some stores put the brand only inside the name: use it when it is a brand seen elsewhere
        for n in (2, 1):
            cand = "".join(words[:n])
            if len(words) > n and cand in vocab:
                brand, drop = cand, {_stem(w) for w in words[:n]}
                break
    toks = {_stem(w) for w in words if w not in NOISE} - drop - NOISE
    return {"brand": brand, "tokens": toks, "size": _size_key(rec)}


def _similarity(a, b):
    """0 when the two token sets must not be merged, else a score in (0, 1]."""
    ta, tb = a["tokens"], b["tokens"]
    if not ta or not tb:
        return 0.0
    diff = ta ^ tb
    if any(w in VARIANT_WORDS or w.isdigit() for w in diff):
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
            if f["size"] and f["brand"]:
                blocks.setdefault((f["size"], f["brand"]), []).append((k, store, f))
    owner = {k: k for k in clusters}               # union-find over cluster keys

    def find(x):
        while owner[x] != x:
            owner[x] = owner[owner[x]]
            x = owner[x]
        return x

    for members in blocks.values():
        if len(members) < 2:
            continue
        pairs = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                (k1, s1, f1), (k2, s2, f2) = members[i], members[j]
                if s1 == s2 or k1 == k2:
                    continue
                sim = _similarity(f1, f2)
                if sim:
                    pairs.append((sim, k1, k2))
        for sim, k1, k2 in sorted(pairs, reverse=True):
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
    return len(all_rows), len(changes), len(compare)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["woolworths", "newworld", "paknsave", "newgumsarn"])
    ap.add_argument("--probe", choices=["woolworths", "newworld", "paknsave", "newgumsarn"])
    ap.add_argument("--match-report", action="store_true", help="show how well products match across stores, from the last scrape")
    ap.add_argument("--fixture", help="directory of saved raw responses (<store>.json) for an offline run")
    args = ap.parse_args()

    if args.match_report:
        match_report()
        return

    cfg = json.loads((ROOT / "config.json").read_text())
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
        if store == "woolworths":
            if not probe:
                manual = load_manual_woolworths()
                if manual:
                    store_times["woolworths"] = manual[1]
                    print(f"  woolworths: using uploaded woolworths.json from {manual[1]} ({len(manual[0])} products)", file=sys.stderr)
                    return manual[0]
            return scrape_woolworths(c, gcfg, session, probe)
        if store == "newgumsarn":
            return scrape_shopify(store, c, gcfg, session, probe)
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
