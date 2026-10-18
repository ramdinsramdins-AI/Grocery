# Shelf Check scraper

Collects shelf prices from Woolworths NZ, New World and PAK'nSAVE, and from the Asian grocers New Gum Sarn, TXG Mall, NJK and FromK, three times a day and writes JSON that the site in `docs/` reads. The stores and how each is read are listed in `config.json` (`platform`: shopify, woocommerce or magento; Foodstuffs and Woolworths have their own code).

## Status: untested against the live sites

The size parsing, per-100g maths, price-change history and cross-store grouping are tested offline (`python test_scraper.py`).
The request shapes for the three stores were built from public notes on how each site loads its own product lists, and I could not call the live sites from where I built this. Do the probe step below before the first full run.

## First run

```
pip install requests
export SCRAPER_CONTACT="you@example.com"      # goes in the User-Agent so the stores can reach you
python scraper.py --probe woolworths           # saves raw/woolworths.json
python scraper.py --probe newworld
python scraper.py --probe paknsave
```

Open each file in `raw/` and check that the price, size and unit price fields are where the parser expects them:

- Woolworths: `products.items[].price.salePrice / originalPrice`, `size.volumeSize`, `size.cupPrice`, `size.cupMeasure`
- New World and PAK'nSAVE: `products[].singlePrice.price` (in cents), `singlePrice.comparativePrice`, `displayName`, `promotions[]`

If a field name differs, change it in `woolworths_parse` or `foodstuffs_parse`. If a department or category name returns nothing, fix it in `config.json` (the names must match the store's own menu).
Then run `python scraper.py --store paknsave` for one store, check `docs/data/latest.json`, and only then run all three.

## Scheduling

Option A, GitHub Actions: push this folder to a private GitHub repo. `.github/workflows/scrape.yml` runs at 6am, 12pm and 6pm NZ time and commits the data. Add a repo secret `SCRAPER_CONTACT`.
Supermarket sites often block cloud and datacentre IP addresses. If Actions runs come back with 403 or 429, use option B.

Option B, a machine at home (laptop, Raspberry Pi) or a small VPS:

```
crontab -e
0 6,12,18 * * * cd /path/to/shelf-check-scraper && SCRAPER_CONTACT=you@example.com python3 scraper.py >> scrape.log 2>&1
```

## Woolworths (collected from your own browser)

Woolworths answers only real web browsers (not GitHub's servers, and not scripts on a home computer either), so the scheduled run cannot fetch it.
Instead, about once a week:

1. Open https://www.woolworths.co.nz and click the **Collect Woolworths prices** button on your bookmarks bar (set it up once from `woolworths-button.html`). Keep the tab open for 10 to 15 minutes; it downloads `woolworths.json`.
2. On the home PC, the Windows task "Shelf Check - upload Woolworths prices" notices the new file within 10 minutes, sends it to the repo's main folder, moves old price files to the Recycle Bin, and shows a message. Switch it on or off with `install-woolworths-uploader.ps1` (`-Remove` to switch off).

Without the task, upload `woolworths.json` to the main folder of the repo (not inside `docs`) by hand. The next scrape reads it, skips the network call, and the site shows the date the Woolworths prices are from.
The scraper ignores the file once it is more than 7 days old, so stale prices are never shown as current.

## NJK (collected on the home PC)

NJK refuses GitHub's servers but answers a home connection, and plain scripts work there (no browser needed). So `config.json` marks it `"collect_at_home": true`, and the scheduled run reads `njk.json` from the repo's main folder instead of asking NJK.
The Windows task "Shelf Check - collect NJK prices" makes that file at 11 am and 5 pm (or when the PC is next on): it runs `python scraper.py --collect-home <folder>` with the newest code from GitHub and pushes `njk.json`. Nothing to click. It shows a message only when something goes wrong, and it pauses itself if NJK ever blocks the home PC too.
Switch it on (it also collects once straight away) or off with `install-collect-at-home.ps1` (`-Remove` to switch off). Log: `%LOCALAPPDATA%\ShelfCheck\collect-at-home.log`.

## The website

`docs/index.html` is the Shelf Check site. It reads `docs/data/compare.json` and `docs/data/latest.json`, which the scraper rewrites on every run.
The folder ships with sample prices, and the site says so in a yellow banner. The first real scrape replaces them.

To publish it with GitHub Pages: push this folder to a GitHub repo, open Settings, then Pages, and choose "Deploy from a branch", branch `main`, folder `/docs`.
GitHub Pages on a private repo needs a paid GitHub plan, and a published site is public. Think about the terms-of-use point below before you publish scraped prices.

To look at it locally: `cd docs && python3 -m http.server 8000`, then open http://localhost:8000.

## Output (in `docs/data/`)

- `latest.json` every product from the last run, with `unit_price` and `unit_basis` (`100g`, `100ml` or `ea`)
- `history.jsonl` one line per price change, so the history stays small
- `compare.json` products found at two or more stores, which is what the site lists

## Things to know

- **Terms of use.** Read each store's website terms before you run this or publish the data. robots.txt does not block the product API paths for Woolworths or PAK'nSAVE, but robots.txt is a courtesy signal and not permission, and the terms may restrict automated access or reuse. The scraper waits 2 to 4 seconds between requests, identifies itself, and stops on 403 or 429 instead of working around a block. Keep it that way.
- **Prices vary by store.** Each run uses one New World and one PAK'nSAVE store (set `store_id` in `config.json`; the defaults are Papakura). Woolworths prices are whatever its site shows by default. Say which stores the numbers come from on your site.
- **Matching products across stores.** Pass 1 groups identical brand + name words + size. Pass 2 (fuzzy) merges products with the same pack size and brand whose names are similar, and refuses when a variant word (light, organic, vanilla...) or a number differs. Fuzzy groups are tagged `"_m": "fuzzy"` and the site shows "Check it is the same product". After a scrape run `python scraper.py --match-report` to see match rates per store, sample fuzzy matches and the nearest misses. Barcodes would be better if an API exposes them.
- **Endpoints can change** without notice. When a store starts returning empty results, run `--probe` again and compare.

## Recipes

`docs/recipes.html` is a second page: pick recipes, set servings, and get one combined shopping list with the cheapest pack sizes and the cheapest store plans.

- `docs/data/recipes.json` holds the recipes (57 so far, original text, including 10 each Chinese, Japanese and Thai, tagged by cuisine). Each has ingredients as `{item, qty, unit}` where `item` is an id from `ingredients.json`. Add a photo by setting `photo` (see `docs/photos/README.md`).
- `ingredients.json` (repo root) says which supermarket products count as each ingredient (`include` groups, `exclude` words, `base` unit g/ml/ea, `units` conversions such as 1 onion = 150 g, `pantry` = assumed owned).
- The scraper turns those rules into `docs/data/ingredient_products.json` (the pack sizes and prices on sale at each store). The sample file shipped in the repo is replaced on the first real run.
- The page adds up what the chosen recipes need per ingredient, then finds the cheapest combination of that store's packs that covers it (for example 700 g of chicken with 500 g and 1 kg packs costs 1 x 1 kg, 300 g left over). Items sold loose by weight are priced exactly. It lists leftovers and other recipes that could use them.
- To review what was picked: `python scraper.py --ingredient-report`. Tests: `python test_ingredients.py` (rules) and `node test_recipes.js` (pack calculator).

## Languages

- Both pages have a language button with flags: English, Mandarin, Japanese, Thai, Hindi, Te Reo Māori, Filipino, Korean, French, German, Russian and Spanish. It changes the site's own text, recipe names, methods, notes, ingredient names and tags. The choice is remembered in the browser (localStorage `shelfcheck-lang`).
- `docs/i18n.js` draws the menu and flags and looks text up; `docs/i18n/<code>.json` holds one language (`ui`, `tags`, `ingredients`, `recipes`). The English text in the pages is the key, and anything missing shows in English.
- Product names stay as the stores write them, except that names in Chinese, Japanese or Korean (NJK, FromK) are put into English by the scraper on every save: `translations.json` (repo root) lists the names that are only in Chinese, and for mixed names the English part is kept. Add a line to `translations.json` when a new Chinese-only name appears.
- `node test_i18n.js` checks every language file against the pages (missing or unused phrases, placeholders such as `{price}`, tags, ingredients, recipe steps). `node test_i18n.js --keys` prints every phrase a new language file needs. After changing page text or adding recipes, the test lists what each language is missing.
- The translations were written by Claude (AI) and have not been checked by native speakers. Te Reo Māori in particular should be reviewed by a fluent speaker.
