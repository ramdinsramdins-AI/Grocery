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

# output writer: history only records changes, a failed store keeps its old rows, compare groups multi-store items
with tempfile.TemporaryDirectory() as d:
    s.DATA = pathlib.Path(d)
    rows = s.woolworths_parse(w) + s.foodstuffs_parse("paknsave", f)
    n, changed, groups = s.write_outputs(rows, "t1")
    assert (n, changed, groups) == (2, 2, 1), (n, changed, groups)
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

print("all checks passed")
