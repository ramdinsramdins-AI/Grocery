// Collects Woolworths NZ shelf prices from your own browser and downloads woolworths.json.
// Run it on https://www.woolworths.co.nz (any page of that site), in the browser console.
// It asks for one page of 48 products every 2 to 4 seconds and stops straight away if the site says no.
(async () => {
  const DEPARTMENTS = ["fruit-veg", "meat-poultry", "fish-seafood", "fridge-deli", "bakery", "frozen", "pantry", "drinks", "health-body", "cleaning-homeware"];
  const MAX_PAGES = 60;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const items = [];
  const seen = new Set();

  for (const dept of DEPARTMENTS) {
    let got = 0;
    for (let page = 1; page <= MAX_PAGES; page++) {
      await sleep(2000 + Math.random() * 2000);
      const url = `/api/v1/products?target=browse&inStockProductsOnly=false&size=48&page=${page}&dasFilter=Department;;${dept};false`;
      const r = await fetch(url, { headers: { "x-requested-with": "OverlayScrollbars", accept: "application/json" } });
      if (r.status === 403 || r.status === 429) {
        console.log(`Woolworths said no (HTTP ${r.status}). Stopping. Nothing was downloaded.`);
        return;
      }
      if (!r.ok) {
        console.log(`${dept} page ${page}: HTTP ${r.status}. Skipping the rest of this department.`);
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

  if (!items.length) {
    console.log("No products collected, so no file was made. Tell Claude what the lines above say.");
    return;
  }
  const blob = new Blob([JSON.stringify({ collected_at: new Date().toISOString(), products: { items } })], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "woolworths.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  console.log(`Done. ${items.length} products saved to woolworths.json in your Downloads folder.`);
})();
