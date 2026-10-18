// Checks the translations in docs/i18n/*.json against the text the pages use. Run: node test_i18n.js
// node test_i18n.js --keys prints every English phrase the pages translate (what a new language file needs).
const fs = require("fs"), assert = require("assert"), path = require("path");
const docs = path.join(__dirname, "docs");
const read = (f) => fs.readFileSync(path.join(docs, f), "utf8").replace(/\r\n/g, "\n");

// the English phrases: T(...)/TH(...) calls (every string literal in the first argument, so all sides of a ternary
// count), data-i18n text, data-i18n-ph placeholders, data-i18n-aria labels, aisle names and recipe units
function phrases(src) {
  const out = new Set();
  const call = /\b(?:T|TH|t)\(/g;
  let m;
  while ((m = call.exec(src))) {
    let i = m.index + m[0].length, depth = 0;
    for (; i < src.length; i++) {
      const c = src[i];
      if (c === '"' || c === "'") {
        let j = i + 1, s = "";
        while (src[j] !== c) { if (src[j] === "\\") { s += src[j + 1]; j += 2; } else s += src[j++]; }
        out.add(s);
        i = j;
      } else if (c === "(" || c === "{" || c === "[") depth++;
      else if (c === ")" || c === "}" || c === "]") { if (depth === 0) break; depth--; }
      else if (c === "," && depth === 0) break;
    }
  }
  for (const [, attrs, text] of src.matchAll(/<(?:[a-z0-9]+)([^>]*\bdata-i18n\b[^>]*)>([^<]*)(?=<)/g)) if (/\bdata-i18n(?=[\s>])/.test(attrs + ">")) out.add(text.trim());
  for (const [, ph] of src.matchAll(/placeholder="([^"]*)"[^>]*data-i18n-ph/g)) out.add(ph);
  for (const [, al] of src.matchAll(/aria-label="([^"]*)"[^>]*data-i18n-aria/g)) out.add(al);
  return out;
}
const keys = new Set([...phrases(read("index.html")), ...phrases(read("recipes.html")), ...phrases(read("i18n.js"))]);
const aisles = [...read("index.html").matchAll(/^ \["([^"]+)",\//gm)].map((x) => x[1]);
aisles.forEach((a) => keys.add(a));
["tsp", "tbsp", "cup", "pinch", "each", "clove", "stalk", "slice", "can", "g", "ml"].forEach((u) => keys.add(u));
keys.delete("");
for (const k of [...keys]) if (/^(no-cache|data\/|i18n\/|en|status|count|grid|list|after|plans|bk|items|sel|chips|aisles|lang)/.test(k) && !/ /.test(k)) keys.delete(k);

if (process.argv.includes("--keys")) { console.log(JSON.stringify([...keys].sort(), null, 1)); process.exit(0); }

const recipes = JSON.parse(read("data/recipes.json")).recipes;
const ingredients = Object.keys(JSON.parse(fs.readFileSync(path.join(__dirname, "ingredients.json"), "utf8")).ingredients);
const tags = [...new Set(recipes.flatMap((r) => r.tags))];
const holes = (s) => (s.match(/\{\w+\}/g) || []).sort().join(" ");
const langs = fs.readdirSync(path.join(docs, "i18n")).filter((f) => f.endsWith(".json"));
const codes = [...read("i18n.js").matchAll(/code: "(\w+)"/g)].map((x) => x[1]).filter((c) => c !== "en");
assert.deepStrictEqual(langs.map((f) => f.replace(".json", "")).sort(), codes.slice().sort(), "one file per language in the menu");
let problems = 0;
const say = (msg) => { problems++; console.log(msg); };
for (const f of langs) {
  const d = JSON.parse(read("i18n/" + f));
  for (const k of keys) {
    if (!d.ui || !(k in d.ui)) say(`${f}: missing "${k}"`);
    else if (holes(d.ui[k]) !== holes(k)) say(`${f}: "${k}" has placeholders ${holes(d.ui[k]) || "none"}`);
  }
  for (const k of Object.keys(d.ui || {})) if (!keys.has(k)) say(`${f}: "${k}" is not used by the pages any more`);
  for (const t of tags) if (!(d.tags || {})[t]) say(`${f}: missing tag "${t}"`);
  for (const id of ingredients) if (!(d.ingredients || {})[id]) say(`${f}: missing ingredient "${id}"`);
  for (const r of recipes) {
    const x = (d.recipes || {})[r.id];
    if (!x || !x.name || (r.blurb && !x.blurb)) { say(`${f}: recipe "${r.id}" missing or without name/blurb`); continue; }
    if (!x.method || x.method.length !== r.method.length) say(`${f}: recipe "${r.id}" has ${x.method ? x.method.length : 0} method steps, English has ${r.method.length}`);
    for (const n of Object.keys(x.notes || {})) if (!r.ingredients[n] || !r.ingredients[n].note) say(`${f}: recipe "${r.id}" note ${n} has no English note`);
    r.ingredients.forEach((ing, n) => { if (ing.note && !(x.notes || {})[n]) say(`${f}: recipe "${r.id}" missing note ${n}`); });
  }
}
assert.strictEqual(problems, 0, problems + " translation problems: see above");
console.log(`translations: ${langs.length} languages, each with ${keys.size} phrases, ${tags.length} tags, ${ingredients.length} ingredients, ${recipes.length} recipes`);
