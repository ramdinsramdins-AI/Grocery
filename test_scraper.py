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

# speed: a full-size run (30k products, many sharing a size) must group in a few seconds
import random, time
_rnd = random.Random(3)
_big = [s.make_record(st, str(i), f"Product {_rnd.randint(0, 9000)} Item{_rnd.randint(0, 40)}", f"Brand{_rnd.randint(0, 120)}", f"{_rnd.choice([250, 500, 1000])}g", 3.0)
        for st in ("woolworths", "newworld", "paknsave") for i in range(10000)]
_t0 = time.time(); s.group_records(_big); assert time.time() - _t0 < 20, time.time() - _t0

print("all checks passed")
