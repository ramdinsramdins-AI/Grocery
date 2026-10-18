"""Checks that ingredients.json picks the right supermarket products (and skips look-alikes). Run: python test_ingredients.py"""
import json, sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import scraper as s
cat = json.load(open(str(pathlib.Path(__file__).parent / "ingredients.json")))["ingredients"]
def R(name, brand, size, price=5.0, store="newworld", up=None, basis=None):
    r = s.make_record(store, name+size, name, brand, size, price)
    if up is not None: r["unit_price"], r["unit_basis"] = up, basis
    return r
# (ingredient, should match?, name, brand, size)
cases = [
 ("chicken-breast",1,"Chicken Breast Fillets Skinless","Tegel","1kg"), ("chicken-breast",1,"Fresh Chicken Breast","Inghams","500g"),
 ("chicken-breast",0,"Chicken Breast Nuggets","Tegel","400g"), ("chicken-breast",0,"Crumbed Chicken Breast Schnitzel","Tegel","500g"), ("chicken-breast",0,"Butter Chicken Sauce","Pams","350g"),
 ("chicken-thigh",1,"Chicken Thigh Fillets","Tegel","1kg"), ("chicken-thigh",0,"Chicken Thigh Bone In Marinated BBQ","Tegel","800g"),
 ("beef-mince",1,"Beef Mince Premium","Silver Fern","500g"), ("beef-mince",0,"Beef Mince Pie","Papa","200g"), ("beef-mince",1,"NZ Beef Mince","","1kg"),
 ("eggs",1,"Free Range Eggs Size 7","Pams","12 pack"), ("eggs",1,"Eggs Size 6","Farm Fresh","6 pack"), ("eggs",0,"Egg Noodles","Wattie","250g"), ("eggs",0,"Chocolate Eggs","Cadbury","100g"),
 ("milk",1,"Blue Top Milk","Anchor","2L"), ("milk",1,"Standard Milk","Pams","3L"), ("milk",0,"Coconut Milk","Ayam","400ml"), ("milk",0,"Chocolate Milk","Anchor","1L"), ("milk",0,"Oat Milk","Oatly","1L"),
 ("butter",1,"Butter Salted","Anchor","500g"), ("butter",0,"Peanut Butter Crunchy","Pics","380g"), ("butter",0,"Garlic Butter","Pams","100g"),
 ("cream",1,"Cream Thickened","Anchor","300ml"), ("cream",0,"Sour Cream","Meadow Fresh","250g"), ("cream",0,"Ice Cream Vanilla","Tip Top","2L"), ("cream",0,"Hand Cream","Nivea","100ml"),
 ("cheese",1,"Tasty Cheese Block","Mainland","1kg"), ("cheese",1,"Grated Tasty Cheese","Pams","500g"), ("cheese",0,"Cream Cheese","Philadelphia","250g"), ("cheese",0,"Cheese Slices Tasty","Mainland","250g"),
 ("onion",1,"Brown Onions","","1kg"), ("onion",0,"Spring Onions","","each"), ("onion",0,"Onion Rings Frozen","McCain","500g"), ("onion",1,"Onion Red","","per kg"),
 ("potato",1,"Potatoes Agria","","2kg"), ("potato",0,"Potato Chips","Bluebird","150g"), ("potato",0,"Sweet Potato","","per kg"), ("potato",0,"Frozen Potato Fries","McCain","1kg"),
 ("rice",1,"Long Grain White Rice","Pams","1kg"), ("rice",1,"Basmati Rice","Tilda","1kg"), ("rice",0,"Rice Crackers","Sunrise","100g"), ("rice",0,"Microwave Rice Basmati Pouch","Uncle Bens","250g"), ("rice",0,"Rice Bubbles","Kelloggs","400g"),
 ("spaghetti",1,"Spaghetti","Barilla","500g"), ("spaghetti",0,"Spaghetti in Tomato Sauce","Wattie","420g"),
 ("tomato-can",1,"Chopped Tomatoes in Juice"," Undre"[:0]+"Value","400g"), ("tomato-can",1,"Diced Tomatoes","Delmaestro","400g"), ("tomato-can",0,"Tomato Pasta Sauce","Ragu","500g"), ("tomato-can",0,"Sun Dried Tomatoes","Nile","200g"),
 ("flour",1,"Plain Flour","Champion","1.5kg"), ("flour",1,"White Flour","Pams","1kg"), ("flour",0,"Self Raising Flour","Champion","1.5kg"), ("flour",0,"Coconut Flour","Bobs","500g"),
 ("olive-oil",1,"Extra Virgin Olive Oil","Bertolli","500ml"), ("olive-oil",0,"Olive Oil Spray","Pams","200ml"), ("olive-oil",0,"Olives Stuffed","Nile","200g"),
 ("soy-sauce",1,"Soy Sauce","Kikkoman","500ml"), ("soy-sauce",1,"Light Soy Sauce","Lee Kum Kee","500ml"),
 ("honey",1,"Clover Honey","Pams","500g"), ("honey",0,"Honey Soy Chicken Sauce","Masterfoods","300g"), ("honey",0,"Honey Nut Cornflakes","Kelloggs","500g"),
 ("tortilla",1,"Tortillas Large","Mission","8 pack"), ("tortilla",1,"Wraps","Pams","6 pack"), ("tortilla",0,"Tortilla Chips","Old El Paso","200g"),
 ("burger-buns",1,"Burger Buns","Molenberg","6 pack"), ("burger-buns",0,"Hot Dog Buns","Molenberg","6 pack"),
 ("bread",1,"Toast Bread White","Tip Top","700g"), ("bread",0,"Bread Crumbs","Pams","200g"), ("bread",0,"Garlic Bread","Pams","350g"),
 ("lettuce",1,"Lettuce Cos","","each"), ("avocado",1,"Avocado Hass","","each"), ("avocado",0,"Avocado Oil","Olivado","250ml"), ("lemon",1,"Lemons","","each"), ("lemon",0,"Lemon Juice","Pams","250ml"),
 ("mozzarella",1,"Mozzarella Shredded","Perfect Italiano","250g"), ("parmesan",1,"Parmesan Grated","Perfect Italiano","100g"),
 ("kidney-beans",1,"Red Kidney Beans","Delmaestro","400g"), ("chickpeas",1,"Chickpeas","Delmaestro","400g"), ("chickpeas",0,"Hummus Chickpea Dip","Pams","200g"),
 ("coconut-milk",1,"Coconut Milk","Ayam","400ml"), ("coconut-milk",1,"Coconut Cream","Ayam","270ml"),
 ("chicken-stock",1,"Chicken Stock Liquid","Campbells","1L"), ("chicken-stock",0,"Chicken Stock Cubes","Continental","12 pack"),
 ("noodles",1,"Hokkien Noodles","Fantastic","440g"), ("noodles",0,"Instant Noodles Chicken Flavour","Maggi","5 pack"),
 ("penne",1,"Penne Rigate","Barilla","500g"), ("penne",1,"Macaroni","Pams","500g"),
 ("pumpkin",1,"Pumpkin Butternut","","per kg"), ("carrot",1,"Carrots","","1kg"), ("broccoli",1,"Broccoli","","each"), ("mushroom",1,"Button Mushrooms","","200g"),
 ("spinach",1,"Baby Spinach","Pams","120g"), ("capsicum",1,"Capsicum Red","","each"), ("tomato-fresh",1,"Tomatoes Truss","","per kg"), ("tomato-fresh",0,"Tomato Sauce","Wattie","500ml"),
 ("zucchini",1,"Zucchini","","per kg"), ("banana",1,"Bananas","","per kg"), ("ginger",1,"Ginger","","per kg"), ("ginger",0,"Ginger Beer","Bundaberg","4 pack"),
 ("sausages",1,"Pork Sausages","Hellers","12 pack"), ("sausages",0,"Sausage Rolls","Papa","6 pack"), ("bacon",1,"Streaky Bacon","Hellers","250g"), ("bacon",0,"Bacon Bits","Pams","100g"),
 ("ham",1,"Champagne Ham Sliced","Hellers","200g"), ("salmon-fillet",1,"Salmon Fillets Skin On","","400g"), ("salmon-fillet",0,"Smoked Salmon Fillet","","200g"),
 ("tuna-can",1,"Tuna in Springwater","Sirena","185g"), ("tuna-can",0,"Tuna Cat Food","Whiskas","85g"),
 ("yoghurt",1,"Natural Unsweetened Yoghurt","Fresh n Fruity","1kg"), ("yoghurt",1,"Greek Yoghurt Plain","Puhoi","500g"), ("yoghurt",0,"Strawberry Yoghurt","Yoplait","6 pack"),
 ("oats",1,"Rolled Oats","Pams","1kg"), ("oats",1,"Quick Oats","Uncle Tobys","750g"), ("oats",0,"Oat Milk","Oatly","1L"),
 ("salt",1,"Salt Iodised","Pams","500g"), ("salt",0,"Salt & Vinegar Chips","Bluebird","150g"), ("pepper",1,"Black Pepper Ground","Masterfoods","50g"), ("pepper",0,"Capsicum Red Pepper","","each"),
 ("sugar",1,"White Sugar","Chelsea","1.5kg"), ("sugar",0,"Sugar Free Gum","Extra","14pk"), ("baking-powder",1,"Baking Powder","Edmonds","200g"), ("cornflour",1,"Cornflour","Edmonds","300g"),
 ("curry-powder",1,"Curry Powder","Masterfoods","50g"), ("garam-masala",1,"Garam Masala","Masterfoods","40g"), ("ground-cumin",1,"Ground Cumin","Masterfoods","30g"), ("paprika",1,"Paprika","Masterfoods","30g"),
 ("chilli-powder",1,"Chilli Powder","Masterfoods","30g"), ("mixed-herbs",1,"Mixed Herbs","Masterfoods","15g"), ("tomato-paste",1,"Tomato Paste","Pams","140g"),
 ("tomato-paste",0,"watties chopped tomatoes in purée","watties","400g"),
 ("vegetable-oil",1,"Canola Oil","Pams","1L"), ("vegetable-oil",0,"Olive Oil","Bertolli","500ml"), ("flatbread",1,"Pita Bread","Mission","6 pack"), ("frozen-peas",1,"Frozen Peas","Pams","1kg"), ("frozen-peas",0,"Frozen Peas & Corn","Pams","1kg"),
 ("frozen-mixed-veg",1,"Frozen Mixed Vegetables","Pams","1kg"), ("garlic",1,"Garlic Bulb","","each"), ("garlic",0,"Garlic Bread","Pams","350g"), ("beef-strips",1,"Beef Stir Fry Strips","","400g"),
 # look-alikes seen in the first real scrape (October 2026)
 ("lemon",0,"Tie-Tops Lemon Citrus Fresh Kitchen Tidy Liners 30pk","Big Black Sacks","30pk"), ("lemon",0,"Rocketslaw Salad with Creamy Lemon Mayonnaise","","350g"),
 ("banana",0,"Sunscreen Sport SPF 50+","Banana Boat","200g"), ("banana",0,"Bobby Bananas Bunch","Dole","each"), ("banana",1,"Bananas","","per kg"),
 ("eggs",0,"Non Stick Egg Rings","Pams","4pk"), ("cream",0,"Miracle BB Cream Light","mcobeauty","30ml"), ("cream",1,"Cream Fresh","Woolworths","300ml"),
 ("chicken-breast",0,"Chicken Breast Kyivs Garlic Butter","Ingham's","350g"), ("sausages",0,"Mild Curry Sausages Recipe Base Sachet","Maggi","29g"),
 ("sausages",0,"Spaghetti With Sausages","Wattie's","420g"), ("bacon",0,"Bacon Bones","","per kg"), ("onion",0,"Caramelised Onion Hummus","Lisa's","380g"),
 ("pumpkin",0,"Chicken & Pumpkin In Broth Adult Cat Food","Farmers Market","80g"), ("potato",0,"Pumpkin Potato & Beef 8+ Months","Only Organic","170g"),
 ("tuna-can",0,"Smoked Flavoured Tuna","Pams","95g"), ("tuna-can",0,"Albacore Tuna Heads","NZ","1kg"), ("salt",0,"Canned Chicken Oil & Sea Salt","Woolworths","85g"),
 ("pepper",0,"Cracked Pepper Hot Smoked Salmon","Pams","150g"), ("mushroom",0,"Po Ku Mushroom","Tiger King","425g"), ("coriander",1,"Coriander","The Fresh Grower","100g"),
 ("basil",1,"Basil Living Plant","Fresh Herb","each"), ("carrot",1,"Carrots","","per kg"), ("ginger",1,"Ginger Whole","Fresh Vegetable","min order 0.12kg"),
 # Asian recipe ingredients, names from the seven stores (October 2026)
 ("fish-sauce",1,"Fish Sauce","Squid","300ml"), ("fish-sauce",0,"Squid Brand Fish Sauce For Vegan","","180ml"),
 ("oyster-sauce",1,"Panda Brand Oyster Sauce","Lee Kum Kee","510g"), ("oyster-sauce",0,"Doll Fried Noodle Oyster Sauce","","118g"),
 ("sesame-oil",1,"Pure Sesame Oil","Lee Kum Kee","207ml"), ("sesame-oil",0,"Sesame Oil Roasted Seaweed Snack","Chongga","40g"),
 ("mirin",1,"Mirin Seasoning","Obento","250ml"), ("mirin",0,"Soda Mix Mirinda","Soda Stream","440ml"),
 ("rice-vinegar",1,"Rice Wine Vinegar","Obento","250ml"), ("rice-vinegar",0,"Sea Salt & Vinegar Flavoured Rice Crackers","Peckish","90g"),
 ("shaoxing-wine",1,"Shaoxing Hua Diao Cooking Wine Premium","FY","640ml"), ("shaoxing-wine",0,"Vinegar Rice Wine","Obento","250ml"),
 ("hoisin-sauce",1,"Hoisin Sauce","Ayam","210ml"), ("hoisin-sauce",0,"Hoisin Pork & Cabbage Dumplings","KungFood","12pk"),
 ("chilli-bean-paste",1,"Chili Bean Sauce","Lee Kum Kee","226g"), ("chilli-bean-paste",0,"Chilli Sauce With Fermented Beans","Lao Gan Ma","740g"),
 ("five-spice",1,"Five Spice Powder","Soek","113g"), ("five-spice",0,"Five Spice Quail Eggs","LWX","500g"),
 ("japanese-curry-roux",1,"Sauce Mix Mild Golden Curry","S & B","92g"), ("red-curry-paste",1,"Curry Paste Thai Red","Valcom","210g"),
 ("red-curry-paste",0,"Yellow Curry Paste","Cock","500g"), ("green-curry-paste",1,"Green Curry Paste","NJ","100g"),
 ("tofu",1,"Firm Tofu","Pams","450g"), ("tofu",0,"Juicy Stinky Tofu Classic Original","Weilong","360g"), ("tofu",0,"Fragrance Free Tofu Natural Cat Litter","VitaPet","7l"),
 ("rice-noodles",1,"Rice Stick Noodles","Trident","250g"), ("rice-noodles",0,"Vietnamese Pho Chicken Flavour Rice Noodles","Trident","50g"),
 ("udon",1,"Japanese Udon Noodles","Trident","2 x 200g"), ("udon",0,"Tempura Udon Big Bowl","Nongshim","111g"),
 ("sushi-rice",1,"Sushi Rice","Mama San","1kg"), ("sushi-rice",0,"Brown Rice Calrose Medium Grain","SunRice","1kg"),
 ("prawns",1,"Raw Prawn Cutlets","Shore Mariner","500g"), ("prawns",0,"Prawn Crackers Small","Gold Plum","227g"),
 ("pork-mince",1,"Pork Mince","Hellers","400g"), ("pork-mince",0,"Beef and Pork Mince","","per kg"),
 ("pork-belly",1,"Pork Belly Boneless Rind On","3 Fat Pigs","800g"), ("pork-belly",0,"BBQ Pork Belly Strips","Meat Street","270g"),
 ("pork-belly",1,"woolworths nz free farmed pork belly slices","woolworths","0.35-0.6kg 5-8pc"),
 ("peanuts",1,"Dry Roasted Peanuts","Eta","175g"), ("peanuts",0,"Peanut Pouch","M&M's","380g"),
 ("panko",1,"Panko Breadcrumbs","Pams","220g"), ("panko",0,"Free Range Panko Chicken Tenders","Tegel","750g"),
 ("sesame-seeds",1,"Sesame Seeds","Tasti","100g"), ("sesame-seeds",0,"Sesame Seed Hamburger Buns","","6pk"),
 ("lemongrass",1,"Frozen Lemongrass Sticks","Check","200g"), ("lemongrass",0,"Lemongrass Soap","Ecostore","80g"),
 ("spring-onion",1,"Spring Onions","","each"), ("bok-choy",1,"Shanghai Bok Choy","","each"), ("cucumber",1,"Telegraph Cucumber","","each"),
 ("lime",1,"Limes","","per kg"), ("red-chilli",1,"Red Chillies","","50g"), ("bean-sprouts",1,"Mung Bean Sprouts","Spring Life","200g"),
 ("cabbage",1,"Chinese Cabbage (Wong Bok)","","each"), ("cabbage",0,"Green Cabbage Half","","each"), ("eggplant",1,"Eggplant (Aubergine)","","each"),
]
FRESH_ONLY = [("onion","Brown Onions","","1kg","Pantry"), ("lemon","Lemons","","1kg","Snacks, Treats & Easy Meals"), ("garlic","Garlic","","7pk","Vegetables")]
bad=0
for iid, want, name, brand, size in cases:
    rec = R(name, brand, size)
    if size in ("each","per kg") or size.startswith("min order"):
        rec["size"] = size; rec["unit_basis"] = "ea" if size=="each" else "100g"; rec["unit_price"] = 0.5
        rec["match_key"]="x"
    if cat[iid].get("fresh"): rec["category"] = "Fruit & Vegetables"
    got = s._ingredient_match(rec, cat[iid]) and s._ingredient_pack(rec, cat[iid]) is not None
    if bool(got) != bool(want):
        bad+=1; print(("MISSED " if want else "FALSE+ "), iid, "|", brand, name, size, "| pack:", s._ingredient_pack(rec, cat[iid]), "| rule match:", s._ingredient_match(rec, cat[iid]))
# store aisle checks: fresh produce only from the produce aisle (or Woolworths' "fresh vegetable" brands); never from pet, baby or cleaning aisles
aisle_cases = [(iid, 0, name, brand, size, aisle) for iid, name, brand, size, aisle in FRESH_ONLY] + [
 ("onion",1,"fresh vegetable onions brown","fresh vegetable","1.5kg","uploaded"), ("onion",0,"lisas hummus caramelised onion","lisas","380g","uploaded"),
 ("rice",0,"Chicken & Brown Rice Entree Wet Dog Food","Purina ONE","369g","Pets"), ("milk",0,"Toddler Milk Drink Stage 3","Karicare","900g","Baby & Toddler"),
 ("red-chilli",1,"fresh vegetable chilli red","fresh vegetable","3pack","uploaded"), ("red-chilli",0,"Red Chilli Vegetables","Check","200g","Frozen")]
for iid, want, name, brand, size, aisle in aisle_cases:
    rec = R(name, brand, size); rec["category"] = aisle
    got = s._ingredient_match(rec, cat[iid]) and s._ingredient_pack(rec, cat[iid]) is not None
    if bool(got) != bool(want):
        bad+=1; print(("MISSED " if want else "FALSE+ "), iid, "|", brand, name, size, "| aisle:", aisle)
cases += aisle_cases
# the Asian grocers: TXG Mall's "Vegetables" aisle is fresh produce (New Gum Sarn's is canned); cosmetics and medicine aisles never count
store_cases = [("spring-onion",1,"Spring Onions 50g","","50g","Vegetables","txgmall"), ("spring-onion",0,"Spring Onions 50g","","50g","Vegetables","newgumsarn"),
 ("tofu",0,"Tofu Moisture Mask","X","100g","Cosmetic > Skincare","fromk"), ("peanuts",0,"Peanut Plaster","X","100g","Everyday Essentials > Medicine","njk")]
for iid, want, name, brand, size, aisle, store in store_cases:
    rec = R(name, brand, size, store=store); rec["category"] = aisle
    got = s._ingredient_match(rec, cat[iid]) and s._ingredient_pack(rec, cat[iid]) is not None
    if bool(got) != bool(want):
        bad+=1; print(("MISSED " if want else "FALSE+ "), iid, "|", store, name, "| aisle:", aisle)
cases += store_cases
print(len(cases), "cases,", bad, "wrong")
assert bad == 0, "ingredient rules changed behaviour: see the lines above"

# every recipe uses known ingredients, in units the recipe page can convert
recipes = json.load(open(str(pathlib.Path(__file__).parent / "docs" / "data" / "recipes.json"), encoding="utf-8"))["recipes"]
for r in recipes:
    for x in r["ingredients"]:
        spec = cat.get(x["item"])
        assert spec, f"{r['id']}: unknown ingredient {x['item']}"
        ok = x["unit"] == spec["base"] or x["unit"] in spec.get("units", {}) or (x["unit"] in ("tsp", "tbsp", "cup", "pinch") and spec["base"] != "ea")
        assert ok, f"{r['id']}: no conversion for {x['qty']} {x['unit']} of {x['item']}"
print(len(recipes), "recipes use known ingredients and units")
