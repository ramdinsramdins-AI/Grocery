// Collects Woolworths NZ shelf prices from your own browser and downloads woolworths.json.
// Run it on https://www.woolworths.co.nz (any page of that site): click the "Collect Woolworths prices" bookmark
// (see woolworths-button.html), or paste it into DevTools > Sources > Snippets and run it.
// It asks for one page of 48 products every 2 to 4 seconds and stops straight away if the site says no.
// upload-woolworths.ps1 then sends the downloaded file to GitHub.
(async () => {
  if (!/(^|\.)woolworths\.co\.nz$/.test(location.hostname)) {
    alert("Shelf Check: open www.woolworths.co.nz first, then click the button again.");
    return;
  }
  if (window.__shelfCheckRunning) {
    alert("Shelf Check is already collecting prices in this tab. Wait for it to finish.");
    return;
  }
  window.__shelfCheckRunning = true;
  const bar = document.createElement("div");
  bar.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:12px 16px;background:#1d5c2e;color:#fff;" +
    "font:600 15px/1.4 system-ui,sans-serif;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.3)";
  document.body.appendChild(bar);
  const say = (t, done) => { bar.textContent = "Shelf Check: " + t; if (done) bar.style.background = "#333"; console.log(t); };

  const DEPARTMENTS = ["fruit-veg", "meat-poultry", "fish-seafood", "fridge-deli", "bakery", "frozen", "pantry", "drinks", "health-body", "cleaning-homeware"];
  const MAX_PAGES = 60;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const items = [];
  const seen = new Set();

  for (const [n, dept] of DEPARTMENTS.entries()) {
    let got = 0;
    for (let page = 1; page <= MAX_PAGES; page++) {
      say(`collecting prices, aisle ${n + 1} of ${DEPARTMENTS.length} (${dept}). ${items.length} products so far. ` +
        "Keep this tab open; it takes about 10 to 15 minutes.");
      await sleep(2000 + Math.random() * 2000);
      const url = `/api/v1/products?target=browse&inStockProductsOnly=false&size=48&page=${page}&dasFilter=Department;;${dept};false`;
      let r;
      try {
        r = await fetch(url, { headers: { "x-requested-with": "OverlayScrollbars", accept: "application/json" } });
      } catch (e) {
        console.log(`${dept} page ${page}: ${e}. Skipping the rest of this aisle.`);
        break;
      }
      if (r.status === 403 || r.status === 429) {
        say(`Woolworths said no (HTTP ${r.status}), so it stopped. Nothing was downloaded.`, true);
        window.__shelfCheckRunning = false;
        return;
      }
      if (!r.ok) {
        console.log(`${dept} page ${page}: HTTP ${r.status}. Skipping the rest of this aisle.`);
        break;
      }
      const data = await r.json();
      const list = (data.products && data.products.items) || [];
      if (!list.length) break;
      for (const it of list) {
        if (it.type && it.type !== "Product") continue;
        if (!it.sku || seen.has(it.sku)) continue;
        seen.add(it.sku);
        const s = it.size || {};
        const p = it.price || {};
        items.push({
          type: "Product",
          sku: it.sku,
          name: it.name,
          brand: it.brand,
          size: { volumeSize: s.volumeSize, cupPrice: s.cupPrice, cupMeasure: s.cupMeasure },
          price: { originalPrice: p.originalPrice, salePrice: p.salePrice, isSpecial: p.isSpecial, isClubPrice: p.isClubPrice },
        });
        got++;
      }
    }
    console.log(`${dept}: ${got} products (${items.length} so far)`);
  }

  window.__shelfCheckRunning = false;
  if (!items.length) {
    say("no products were collected, so nothing was downloaded. Try again later.", true);
    return;
  }
  const blob = new Blob([JSON.stringify({ collected_at: new Date().toISOString(), products: { items } })], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "woolworths.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  say(`done. ${items.length} products saved to your Downloads folder as woolworths.json. ` +
    "Your PC sends it to GitHub within 10 minutes. You can close this tab.", true);
})();
