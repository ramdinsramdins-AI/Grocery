"""Offline checks for the parts that do not need the live sites. Run: python test_scraper.py"""
import json
import pathlib
import tempfile

import scraper as s

# size parsing
assert s.parse_size("500g") == (500, "g")
assert s.parse_size("1.5kg") == (1500, "g")
assert s.parse_size("2L") == (2000, "ml")
assert s.parse_size("6 x 330ml") == (1980, "ml")
assert s.parse_size("12 pack") == (12, "ea")
assert s.parse_size("") is None

# unit price from size
assert s.unit_price_from_size(7.49, "500g") == (1.498, "100g")
assert s.unit_price_from_size(4.69, "2L") == (0.2345, "100ml")
assert s.unit_price_from_size(8.90, "12 pack") == (0.7417, "ea")

# store-supplied comparison strings
assert s.unit_price_from_string("$16.48/L") == (1.648, "100ml")
assert s.unit_price_from_string("$90 /kg") == (9.0, "100g")
assert s.unit_price_from_string("$1.50 per 100g") == (1.5, "100g")
assert s.unit_price_from_string("nonsense") is None

# match key ignores word order and filler words
a = s.match_key("Anchor", "Butter Block", "500g")
b = s.match_key("anchor", "block butter", "0.5kg")
assert a == b, (a, b)

# parsers on small fake payloads
w = {"products": {"items": [{"type": "Product", "sku": "1", "name": "Butter", "brand": "Anchor",
     "size": {"volumeSize": "500g", "cupPrice": 1.5, "cupMeasure": "100g"},
     "price": {"originalPrice": 8.99, "salePrice": 7.49, "isSpecial": True}}]}}
r = s.woolworths_parse(w)[0]
assert r["price"] == 7.49 and r["was"] == 8.99 and r["on_special"] and r["unit_basis"] == "100g"

f = {"products": [{"productId": "R1-PNS", "name": "Butter", "brand": "Anchor", "displayName": "500g",
     "singlePrice": {"price": 799, "comparativePrice": {"pricePerUnit": 1598, "unitQuantity": "1kg"}}}]}
r = s.foodstuffs_parse("paknsave", f)[0]
assert r["price"] == 7.99 and r["unit_price"] == 1.598 and r["unit_basis"] == "100g"
# loose produce: size "kg" or "ea" and no comparative price from the store
loose = {"products": [{"productId": "B1", "name": "Bananas", "brand": "", "displayName": "kg", "singlePrice": {"price": 379}},
                      {"productId": "B2", "name": "Broccoli", "brand": "", "displayName": "ea", "singlePrice": {"price": 179}}]}
kg, ea = s.foodstuffs_parse("newworld", loose)
assert (kg["unit_price"], kg["unit_basis"]) == (0.379, "100g") and (ea["unit_price"], ea["unit_basis"]) == (1.79, "ea"), (kg, ea)

# output writer: history only records changes, a failed store keeps its old rows, compare groups multi-store items
with tempfile.TemporaryDirectory() as d:
    s.DATA = pathlib.Path(d)
    rows = s.woolworths_parse(w) + s.foodstuffs_parse("paknsave", f)
    n, changed, groups = s.write_outputs(rows, "t1")
    assert (n, changed, groups) == (2, 2, 1), (n, changed, groups)
    meta = json.loads((s.DATA / "compare.json").read_text())
    assert meta["stores_scraped_this_run"] == ["paknsave", "woolworths"], meta["stores_scraped_this_run"]
    n, changed, groups = s.write_outputs(rows, "t2")
    assert changed == 0
    only_pns = s.foodstuffs_parse("paknsave", f)
    n, changed, groups = s.write_outputs(only_pns, "t3")
    assert n == 2 and groups == 1  # Woolworths rows kept from the earlier run
    assert len((s.DATA / "history.jsonl").read_text().splitlines()) == 2

# the shipped sample data is dropped on the first real run
with tempfile.TemporaryDirectory() as d:
    s.DATA = pathlib.Path(d)
    (s.DATA / "latest.json").write_text(json.dumps({"generated_at": "sample", "products": [
        {"store": "woolworths", "id": "s1", "price": 1.0, "was": None, "club": None, "match_key": "x|?"}]}))
    n, changed, groups = s.write_outputs(s.foodstuffs_parse("paknsave", f), "t1")
    assert n == 1, n

assert s._category_names({"categories": [{"name": "Fruit & Veg", "children": [{"name": "Apples"}]}, {"name": "Bakery"}]}) == ["Fruit & Veg", "Bakery"]

# Foodstuffs search stops at 1,000 hits: a capped category is re-queried per sub-category (saved responses, no network)
import copy
assert s._category_filter('Pantry > Say "cheese"') == 'category0NI:"Pantry" AND category1NI:"Say \\"cheese\\""'
_fx = json.loads((pathlib.Path(__file__).parent / "fixtures" / "foodstuffs_split.json").read_text(encoding="utf-8"))["responses"]


class _FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, *a, **kw):   # the category list is optional; pretend it is unavailable
        return type("R", (), {"ok": False})()


def _scrape_fixture(responses, categories):
    calls = []

    def post(session, url, delay, **kw):
        if url.endswith("get-current-user"):
            data = {"access_token": "test"}
        else:
            filt, page = kw["json"]["algoliaQuery"]["filters"].split(" AND ", 1)[1], kw["json"]["page"]
            calls.append((filt, page))
            data = responses[filt][page]
        return type("R", (), {"json": lambda self: data})()
    real, s.polite_post = s.polite_post, post
    try:
        recs = s.scrape_foodstuffs("newworld", {"store_id": "x", "categories": categories},
                                   {"max_pages_per_category": 30, "delay_seconds": [0, 0]}, _FakeSession())
    finally:
        s.polite_post = real
    return recs, calls


_P = 'category0NI:"Pantry"'
_CHOC = _P + ' AND category1NI:"Chocolate, Sweets & Chewing Gum"'
_SPICE = _P + ' AND category1NI:"Spices, Seasoning & Coatings"'
recs, calls = _scrape_fixture(_fx, ["Pantry"])
assert calls == [(_P, 0), (_P + ' AND category1NI:"Chips, Nuts & Snacks"', 0),
                 (_CHOC, 0), (_CHOC + ' AND category2NI:"Single Chocolate Bars & Sweets"', 0),
                 (_CHOC + ' AND category2NI:"Chocolate Blocks"', 0),
                 (_SPICE, 0), (_SPICE, 1), (_P + ' AND category1NI:"World Foods"', 0)], calls
ids = [r["id"] for r in recs]
assert len(ids) == len(set(ids)) == 14, ids   # Taco Spice Mix is under Spices and World Foods, Bluebird chips under Pantry and Chips
assert {r["category"] for r in recs} == {"Pantry"}
assert {"Mild Curry Powder", "Fajita Spice Mix", "Chocolate Block"} <= {r["name"] for r in recs}
# the deepest level (category2NI) has nothing below it to split by: keep what the search gives
_deep = copy.deepcopy(_fx)
_deep[_CHOC + ' AND category2NI:"Chocolate Blocks"'][0]["totalHits"] = 1000
recs, calls = _scrape_fixture(_deep, ["Pantry > Chocolate, Sweets & Chewing Gum > Chocolate Blocks"])
assert len(calls) == 1 and len(recs) == 2, (calls, recs)

# uploaded woolworths.json: used when fresh, ignored when old or malformed
import datetime as dt
with tempfile.TemporaryDirectory() as d:
    s.MANUAL_WOOLWORTHS = pathlib.Path(d) / "woolworths.json"
    assert s.load_manual_woolworths() is None  # missing
    fresh = dict(w, collected_at=dt.datetime.now(dt.timezone.utc).isoformat())
    s.MANUAL_WOOLWORTHS.write_text(json.dumps(fresh))
    recs, at = s.load_manual_woolworths()
    assert recs[0]["price"] == 7.49 and at == fresh["collected_at"]
    old = dict(w, collected_at=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=9)).isoformat())
    s.MANUAL_WOOLWORTHS.write_text(json.dumps(old))
    assert s.load_manual_woolworths() is None  # too old
    s.MANUAL_WOOLWORTHS.write_text("not json")
    assert s.load_manual_woolworths() is None  # unreadable
    s.DATA = pathlib.Path(d)
    s.write_outputs(s.woolworths_parse(w), "t1", {"woolworths": "2026-10-12T00:00:00Z"})
    assert json.loads((s.DATA / "compare.json").read_text())["store_times"] == {"woolworths": "2026-10-12T00:00:00Z"}

# Shopify feed: single-unit variant chosen, bulk variants skipped, sale price from compare_at_price
sp = {"products": [{"id": 1, "title": "Coconut Milk UHT 1L", "vendor": "AROY-D", "product_type": "Coconut", "handle": "a",
      "variants": [{"title": "UNIT", "price": "6.99", "compare_at_price": "8.50", "sku": "11", "available": True},
                   {"title": "CARTON/12", "price": "75.90", "compare_at_price": "0.00", "sku": "12", "available": True}]},
     {"title": "Bulk only", "vendor": "X", "handle": "b", "variants": [{"title": "CARTON/12", "price": "50", "sku": "2", "available": True}]}]}
r = s.shopify_parse("newgumsarn", "https://x.nz", sp)
assert len(r) == 1 and r[0]["price"] == 6.99 and r[0]["was"] == 8.5 and r[0]["unit_basis"] == "100ml", r
# TXG Mall puts its own name in "vendor": not a brand
r = s.shopify_parse("txgmall", "https://x.nz", sp, vendor_is_brand=False)
assert r[0]["brand"] is None, r

# WooCommerce Store API (FromK): cents, "[Brand] English / Korean – size", size*count, sale price, out of stock skipped
wp = [{"id": 1, "sku": "F1", "is_in_stock": True, "permalink": "https://fromk.co.nz/shop/grocery/seaweed/x/",
       "name": "[Kwangcheonkim] Lightly Salted Roasted Seaweed / [광천김] 짜지않은 김 &#8211; 4g*16pk",
       "prices": {"price": "1520", "regular_price": "1790", "currency_minor_unit": 2}, "categories": [{"name": "Seaweed"}]},
      {"id": 2, "sku": "F2", "is_in_stock": True, "permalink": "https://fromk.co.nz/shop/grocery/soups-stews/y/",
       "name": "Smart Saving &#8211; [Singsong] Soybean Paste Soup with Crab &#8211; 10g",
       "prices": {"price": "240", "regular_price": "240", "currency_minor_unit": 2}, "categories": [{"name": "Smart Saving"}]},
      {"id": 3, "sku": "F3", "is_in_stock": False, "name": "[X] Gone &#8211; 1kg", "prices": {"price": "100", "currency_minor_unit": 2}}]
r = s.woocommerce_parse("fromk", wp)
assert len(r) == 2, r
assert (r[0]["brand"], r[0]["name"], r[0]["size"], r[0]["price"], r[0]["was"]) == ("Kwangcheonkim", "Lightly Salted Roasted Seaweed", "16 x 4g", 15.2, 17.9), r[0]
assert r[0]["unit_basis"] == "100g" and r[0]["category"] == "Grocery > Seaweed", r[0]
assert (r[1]["brand"], r[1]["name"], r[1]["size"], r[1]["was"]) == ("Singsong", "Soybean Paste Soup with Crab", "10g", None), r[1]

# Magento GraphQL (NJK): in-stock items only, special price as "was", "600ml*12" read as 12 x 600ml
mg = {"data": {"products": {"page_info": {"total_pages": 1}, "items": [
    {"sku": "SP1", "name": "Yueyan Iodized Low Sodium Salt 250g", "stock_status": "IN_STOCK", "url_key": "sp1",
     "categories": [{"name": "Food & Drinks"}, {"name": "Salt & MSG"}],
     "price_range": {"minimum_price": {"final_price": {"value": 0.89}, "regular_price": {"value": 1.49}}}},
    {"sku": "SP2", "name": "TTL Cooking Wine 600ml*12", "stock_status": "IN_STOCK", "url_key": "sp2", "categories": [],
     "price_range": {"minimum_price": {"final_price": {"value": 30.0}, "regular_price": {"value": 30.0}}}},
    {"sku": "SP3", "name": "Sold Out 1kg", "stock_status": "OUT_OF_STOCK", "url_key": "sp3", "categories": [],
     "price_range": {"minimum_price": {"final_price": {"value": 1.0}, "regular_price": {"value": 1.0}}}}]}}}
r = s.magento_parse("njk", "https://www.njk.co.nz", mg)
assert len(r) == 2 and r[0]["price"] == 0.89 and r[0]["was"] == 1.49 and r[0]["unit_price"] == 0.356, r
assert r[0]["category"] == "Food & Drinks > Salt & MSG" and r[0]["url"] == "https://www.njk.co.nz/sp1.html", r[0]
assert s.parse_size(r[1]["size"]) == (7200, "ml"), r[1]

# cross-store matching: real differences in wording still match, look-alike products do not
def _R(store, id, name, brand, size):
    return s.make_record(store, id, name, brand, size, 5.0)
def _joined(a, b):
    return len(s.group_records([a, b])) == 1
for a, b in [
    (_R("woolworths", "1", "Mainland Tasty Cheese Block", None, "500g"), _R("newworld", "2", "Tasty Cheese", "Mainland", "500g")),
    (_R("woolworths", "1", "Rolled Oats", "Mother Earth", "750g"), _R("paknsave", "2", "Rolled Oats", "Motherearth", "750g")),
    (_R("woolworths", "1", "Anchor Blue Top Milk 2L", "Anchor", "2L"), _R("newworld", "2", "Blue Top Milk", "Anchor", "2L")),
    (_R("woolworths", "1", "Free Range Eggs", "Pams", "12 pack"), _R("paknsave", "2", "Egg Free Range", "Pams", "12 pack")),
    (_R("woolworths", "1", "Cream Cheese Original Spread", "Philadelphia", "250g"), _R("newworld", "2", "Original Cream Cheese", "Philadelphia", "250g")),
]:
    assert _joined(a, b), (a["name"], b["name"])
for a, b in [
    (_R("woolworths", "1", "Coca-Cola Zero Sugar", "Coca-Cola", "1.5L"), _R("newworld", "2", "Coca-Cola Classic", "Coca-Cola", "1.5L")),
    (_R("woolworths", "1", "Vanilla Ice Cream", "Tip Top", "2L"), _R("newworld", "2", "Chocolate Ice Cream", "Tip Top", "2L")),
    (_R("woolworths", "1", "Free Range Eggs Size 7", "Pams", "12 pack"), _R("newworld", "2", "Free Range Eggs Size 8", "Pams", "12 pack")),
    (_R("woolworths", "1", "Milk Light Blue", "Anchor", "2L"), _R("newworld", "2", "Milk Blue", "Anchor", "2L")),
    (_R("woolworths", "1", "Tomato Sauce", "Heinz", "500ml"), _R("newworld", "2", "Tomato Sauce", "Watties", "500ml")),
    (_R("woolworths", "1", "Butter", "Anchor", "500g"), _R("newworld", "2", "Butter", "Anchor", "250g")),
    (_R("woolworths", "1", "Rolled Oats Organic", "Mother Earth", "750g"), _R("newworld", "2", "Rolled Oats", "Mother Earth", "750g")),
    (_R("woolworths", "1", "Rolled Oats", "Mother Earth", "750g"), _R("woolworths", "2", "Oats Rolled Quick", "Mother Earth", "750g")),
]:
    assert not _joined(a, b), (a["name"], b["name"])
_g = s.group_records([_R("woolworths", "1", "Anchor Blue Top Milk 2L", "Anchor", "2L"), _R("newworld", "2", "Blue Top Milk", "Anchor", "2L")])
assert [g["_m"] for g in _g.values()] in (["exact"], ["fuzzy"])

# Woolworths-style names from the real data (2026-10-15): brand carries the product line, multipacks, loose produce
def _loose(store, id, name, brand, size, price, per, category=None):
    return s.make_record(store, id, name, brand, size, price, store_unit_text=f"${price}/{per}", category=category)
for a, b in [
    # brand prefix: the longer brand's extra words count as name words
    (_R("woolworths", "1", "sealord sensations tuna smoked flavour", "sealord sensations", "185g"), _R("newworld", "2", "Smoked Flavour Tuna", "Sealord", "185g")),
    (_R("woolworths", "1", "jed's plunger grind coffee 3 strong", "jed's", "200g"), _R("newworld", "2", "3 Strong Plunger Coffee", "Jed's Coffee Co.", "200g")),
    (_R("woolworths", "1", "homegrown fruit juice apple 100% pure", "homegrown", "1L"), _R("paknsave", "2", "100% NZ Apple Juice", "The Homegrown Juice Company", "1l")),
    (_R("woolworths", "1", "mccain super fries straight cut", "mccain super", "900g"), _R("newworld", "2", "Superfries Straight Cut Chips", "McCain", "900g")),
    # accents and words written together or apart
    (_R("woolworths", "1", "nescafé classic instant coffee", "nescafé", "100g"), _R("newworld", "2", "Classic Instant Coffee", "Nescafe", "100g")),
    (_R("woolworths", "1", "havana coffee beans kick start", "havana", "180g"), _R("newworld", "2", "KickStart Coffee Beans", "Havana", "180g")),
    # "original" left unsaid on one side
    (_R("woolworths", "1", "trident sweet chilli sauce", "trident", "285mL"), _R("newworld", "2", "Original Sweet Chilli Sauce", "Trident", "285ml")),
    # multipacks: '10pack' = '10 x 100ml'; weight in the name for the whole pack ('71g') or for one item ('24g')
    (_R("woolworths", "1", "juicies tropical ice blocks", "juicies", "10pack"), _R("newworld", "2", "Tropical Ice Blocks", "Juicies", "10 x 100ml")),
    (_R("woolworths", "1", "oxo beef stock cubes 71g", "oxo", "12pack"), _R("newworld", "2", "Beef Flavour Stock Cubes", "Oxo", "71g")),
    (_R("woolworths", "1", "maggi instant gravy mix roast chicken 24g", "maggi", "3pack"), _R("paknsave", "2", "Roast Chicken Flavoured Gravy Mix", "Maggi", "3 x 24g")),
    (_R("woolworths", "1", "vista sparkling water blood orange 330ml", "vista", "8pack"), _R("newworld", "2", "Blood Orange Sparkling Water", "Vista", "8 x 330ml")),
    # loose produce: no pack size, matched per kg or each
    (_loose("woolworths", "1", "fresh fruit bananas yellow loose", "fresh fruit", None, 3.99, "1kg"), _loose("newworld", "2", "Bananas", None, "kg", 3.79, "kg", "Fruit & Vegetables")),
    (_loose("woolworths", "1", "fresh vegetable broccoli head", "fresh vegetable", None, 2.0, "1ea"), _loose("paknsave", "2", "Broccoli", None, "ea", 1.89, "ea", "Fruit & Vegetables")),
]:
    assert _joined(a, b), (a["name"], b["name"])
for a, b in [
    (_R("woolworths", "1", "doritos corn chips original", "doritos", "170g"), _R("paknsave", "2", "Salsa Corn Chips", "Doritos", "170g")),
    (_R("woolworths", "1", "palmolive foaming hand wash raspberry", "palmolive foaming", "250mL"), _R("paknsave", "2", "Foaming Fresh Watermelon Hand Wash", "Palmolive", "250ml")),
    (_R("woolworths", "1", "loreal revitalift anti-wrinkle extra firming day cream", "loreal", "50mL"), _R("newworld", "2", "Revitalift Anti-Wrinkle Extra Firming SPF30 Day Cream", "Loreal", "50ml")),
    (_R("woolworths", "1", "ocean spray low sugar fruit drink cranberry", "ocean spray low sugar", "1.5L"), _R("newworld", "2", "Cranberry Fruit Drink", "Ocean Spray", "1.5l")),
    (_R("woolworths", "1", "anchor sour cream lite 250g", "anchor", "2pack"), _R("newworld", "2", "Lite Sour Cream", "Anchor", "500g")),          # 2 x 250g or 2 x 125g: not a 500g tub
    (_R("woolworths", "1", "vista sparkling water blood orange 330ml", "vista", "8pack"), _R("newworld", "2", "Blood Orange Sparkling Water", "Vista", "330ml")),  # one can
    (_R("newworld", "1", "Ultra Dry Nappies Size 3 6-11kg", "Huggies", "22pk"), _R("paknsave", "2", "Ultra Dry Nappies Size 3 6-11kg", "Huggies", "90pk")),
    (_loose("woolworths", "1", "fresh vegetable cauliflower half", "fresh vegetable", None, 2.2, "1ea"), _loose("newworld", "2", "Cauliflower", None, "ea", 2.59, "ea", "Fruit & Vegetables")),
    (_loose("woolworths", "1", "fresh vegetable carrots", "fresh vegetable", None, 2.19, "1kg"), _loose("newworld", "2", "Carrots", None, "ea", 2.49, "ea", "Fruit & Vegetables")),  # per kg vs each
]:
    assert not _joined(a, b), (a["name"], b["name"])
# a '6pack' with no can size must not pick between two can sizes
_g = s.group_records([_R("woolworths", "1", "coca cola soft drink", "coca cola", "6pack"),
                      _R("newworld", "2", "Soft Drink Cans", "Coca-Cola", "6 x 250ml"), _R("newworld", "3", "Soft Drink Cans", "Coca-Cola", "6 x 330ml")])
assert not any("woolworths" in g for g in _g.values()), _g

# speed: a full-size run (30k products, many sharing a size) must group in a few seconds
import random, time
_rnd = random.Random(3)
_big = [s.make_record(st, str(i), f"Product {_rnd.randint(0, 9000)} Item{_rnd.randint(0, 40)}", f"Brand{_rnd.randint(0, 120)}", f"{_rnd.choice([250, 500, 1000])}g", 3.0)
        for st in ("woolworths", "newworld", "paknsave") for i in range(10000)]
_t0 = time.time(); s.group_records(_big); assert time.time() - _t0 < 20, time.time() - _t0

# a busy shop server (503) is retried after a wait; a block (403/429) is not retried
import requests


def _resp(code, headers=None):
    r = requests.Response()
    r.status_code, r.url, r.headers = code, "https://shop.test/products.json", requests.structures.CaseInsensitiveDict(headers or {})
    return r


class _Replies:
    def __init__(self, *replies):   # status codes, or ready-made responses
        self.replies, self.calls = [r if isinstance(r, requests.Response) else _resp(r) for r in replies], 0

    def request(self, method, url, **kw):
        self.calls += 1
        return self.replies.pop(0)


_waits, _real_sleep = [], s.time.sleep
s.time.sleep = _waits.append
try:
    _sess = _Replies(503, 200)
    assert s._request(_sess, "GET", "https://shop.test/products.json", [0, 0]).status_code == 200 and _sess.calls == 2
    assert _waits[1:] == [10], _waits
    _waits.clear()
    _sess = _Replies(_resp(503, {"Retry-After": "45"}), 200)
    s._request(_sess, "GET", "https://shop.test/products.json", [0, 0])
    assert _waits[1:] == [45], _waits
    _sess = _Replies(503, 503, 503)
    try:
        s._request(_sess, "GET", "https://shop.test/products.json", [0, 0])
        raise AssertionError("three 503s should fail")
    except requests.HTTPError:
        assert _sess.calls == 3
    for _code in (403, 429):
        _sess = _Replies(_code, 200)
        try:
            s._request(_sess, "POST", "https://shop.test/graphql", [0, 0])
            raise AssertionError(f"{_code} should stop the store")
        except s.Blocked:
            assert _sess.calls == 1
finally:
    s.time.sleep = _real_sleep

# stores collected on the home PC (NJK): saved as <store>.json, read back by the scheduled run
_now = "2026-10-18T08:00:00+00:00"
_njk = [s.make_record("njk", str(i), f"Noodles {i} 100g", None, "100g", 1.5) for i in range(10)]
with tempfile.TemporaryDirectory() as _repo, tempfile.TemporaryDirectory() as _out:
    _asked = []

    def _scrape(store, recs=_njk):
        _asked.append(store)
        return recs
    assert s.collect_home(["njk"], _scrape, _out, _now, _repo) == 0 and _asked == ["njk"]
    _recs, _at = s.read_home_file("njk", _out)
    assert _at == _now and [r["id"] for r in _recs] == [r["id"] for r in _njk] and _recs[0]["unit_basis"] == "100g"
    pathlib.Path(_out, "njk.json").replace(pathlib.Path(_repo, "njk.json"))   # now it is "on GitHub"
    # collected 1 hour ago: the site is not asked again
    assert s.collect_home(["njk"], _scrape, _out, "2026-10-18T09:00:00+00:00", _repo) == 0 and _asked == ["njk"]
    assert not pathlib.Path(_out, "njk.json").exists()
    # 6 hours later but only half the products: looks cut short, not saved
    assert s.collect_home(["njk"], lambda st: _njk[:5], _out, "2026-10-18T14:00:00+00:00", _repo) == 1
    assert not pathlib.Path(_out, "njk.json").exists()

    def _blocked(store):
        raise s.Blocked("403 from https://www.njk.co.nz/graphql")
    assert s.collect_home(["njk"], _blocked, _out, "2026-10-18T14:00:00+00:00", _repo) == 1
    assert not pathlib.Path(_out, "njk.json").exists()
    # the scheduled run uses a file up to 7 days old, then reports the store as failed (its last rows are kept)
    _p = pathlib.Path(_repo, "njk.json")
    _fresh = (s.dt.datetime.now(s.dt.timezone.utc) - s.dt.timedelta(days=2)).isoformat(timespec="seconds")
    _p.write_text(json.dumps({"store": "njk", "collected_at": _fresh, "products": _njk}), encoding="utf-8")
    assert len(s.load_home_collection("njk", _repo)[0]) == 10
    _old = (s.dt.datetime.now(s.dt.timezone.utc) - s.dt.timedelta(days=8)).isoformat(timespec="seconds")
    _p.write_text(json.dumps({"store": "njk", "collected_at": _old, "products": _njk}), encoding="utf-8")
    try:
        s.load_home_collection("njk", _repo)
        raise AssertionError("an 8-day-old file should not be used")
    except RuntimeError as e:
        assert "8 days old" in str(e), e
    _p.unlink()
    try:
        s.load_home_collection("njk", _repo)
        raise AssertionError("a missing file should fail the store")
    except RuntimeError:
        pass
assert json.loads((pathlib.Path(__file__).parent / "config.json").read_text())["stores"]["njk"].get("collect_at_home")

print("all checks passed")
