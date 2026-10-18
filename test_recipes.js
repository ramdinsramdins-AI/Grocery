// Checks the pack-size calculator in docs/recipes.html. Run: node test_recipes.js
const fs = require("fs"), assert = require("assert");
const html = fs.readFileSync(__dirname + "/docs/recipes.html", "utf8").replace(/\r\n/g, "\n");   // Git on Windows checks out CRLF
const src = html.match(/<script>([\s\S]*)<\/script>/)[1];
const fn = src.match(/function packPrice[\s\S]*?\n}\n/)[0] + src.match(/function cover[\s\S]*?\n}\n\nfunction planData/)[0].replace(/\n\nfunction planData$/, "");
const cover = new Function("state", fn + "; return cover;")({ member: false });
const pk = (q, p, extra) => Object.assign({ n: q + "g", q, p, c: null, l: 0 }, extra || {});
const chicken = [pk(500, 9.5), pk(1000, 17)];
let r = cover(700, chicken);
assert.strictEqual(r.cost, 17); assert.strictEqual(r.bought, 1000); assert.strictEqual(r.left, 300);   // 700 g -> one 1 kg pack
r = cover(1100, chicken);
assert.strictEqual(r.cost, 26.5); assert.strictEqual(r.bought, 1500);                                 // 1 kg + 500 g beats 3 x 500 g
r = cover(200, chicken);
assert.strictEqual(r.cost, 9.5); assert.strictEqual(r.left, 300);                                      // 200 g -> smallest pack
r = cover(2000, chicken);
assert.strictEqual(r.cost, 34); assert.strictEqual(r.left, 0);
r = cover(300, [pk(100, 2.9, { l: 1 }), pk(500, 9)]);                                                  // loose (by weight) is bought exactly
assert.ok(Math.abs(r.cost - 8.7) < 1e-9 && r.left === 0);
r = cover(500, [pk(100, 1.28, { l: 1, m: 1800 }), pk(100, 1.5, { l: 1 })]);                          // a minimum order is respected:
assert.ok(Math.abs(r.cost - 7.5) < 1e-9 && r.left === 0);                                              // 500 g at $1.50/100g beats 1.8 kg at $1.28
r = cover(2000, [pk(100, 1.28, { l: 1, m: 1800 }), pk(100, 1.5, { l: 1 })]);
assert.ok(Math.abs(r.cost - 25.6) < 1e-9 && r.left === 0);
r = cover(500, [pk(100, 1.28, { l: 1, m: 1800 })]);
assert.ok(Math.abs(r.cost - 23.04) < 1e-9 && r.left === 1300);
assert.strictEqual(cover(100, []), null);

// store plans: there is always a one-store plan; when no store sells everything it names what is missing and is never "best value"
const planSrc = src.match(/function planData[\s\S]*?\n}\n\nfunction allTags/)[0].replace(/\n\nfunction allTags$/, "");
// (fn also carries the page's own needs(), so the stand-in is assigned over it)
const plansFor = (ING) => new Function("STORES", "KEYS", "ING", "state", "fakeNeeds", "isHave", "money", fn + planSrc + "; needs = fakeNeeds; return planData;")(
  { a: "Shop A", b: "Shop B", c: "Shop C" }, ["a", "b", "c"], ING, { member: false, stop: 4 },
  () => Object.fromEntries(Object.keys(ING).map((id) => [id, { amt: 100, uses: [] }])), () => false, (n) => "$" + n.toFixed(2))().plans;
let ps = plansFor({ x: { name: "X", stores: { a: [pk(100, 5)], b: [pk(100, 4)] } }, y: { name: "Y", stores: { c: [pk(100, 3)] } },
                    z: { name: "Z", stores: { a: [pk(100, 2)], c: [pk(100, 2.5)] } } });
let one = ps.find((p) => p.id === "one");
assert.ok(one && one.partial && one.name === "One store: Shop C" && one.a.missing.join() === "x", one);   // C and A each lack one item; C is cheaper
assert.ok(/No single store sells everything\. Shop C has 2 of 3 items; not there: X\./.test(one.note), one.note);
assert.deepStrictEqual(ps.map((p) => p.id), ["one", "two", "all"]);
assert.strictEqual(ps.find((p) => p.rec).id, "two");                                                    // B + C: $9.50 + one $4 stop
ps = plansFor({ x: { name: "X", stores: { a: [pk(100, 5)], b: [pk(100, 6)] } }, y: { name: "Y", stores: { a: [pk(100, 3)], b: [pk(100, 2)] } } });
one = ps.find((p) => p.id === "one");
assert.ok(!one.partial && one.name === "One store: Shop A" && one.note.startsWith("Dearest store with everything is $8.00."), one);
// A to Z order on both pages: letters first, then names starting with a number, then other scripts; numbers in natural order
const sortSrc = (file) => {
  const s = fs.readFileSync(__dirname + "/docs/" + file, "utf8").replace(/\r\n/g, "\n");
  return ["sortText", "nameGroup", "byName"].map((f) => s.match(new RegExp("function " + f + "[\\s\\S]*?\\n"))[0]).join("");
};
assert.strictEqual(sortSrc("index.html"), sortSrc("recipes.html"));
const byName = new Function(sortSrc("index.html") + "; return byName;")();
assert.deepStrictEqual(["19 Crimes Red Blend", "金海林 海帶結50g", "Zucchini", "180 degrees crackers", "apple juice", "\"Pams\" Butter", "2 Minute Noodles", "Banana"].sort(byName),
  ["apple juice", "Banana", "\"Pams\" Butter", "Zucchini", "2 Minute Noodles", "19 Crimes Red Blend", "180 degrees crackers", "金海林 海帶結50g"]);
console.log("recipe pack calculator, store plans and A to Z order: all checks passed");
