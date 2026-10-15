// Checks the pack-size calculator in docs/recipes.html. Run: node test_recipes.js
const fs = require("fs"), assert = require("assert");
const html = fs.readFileSync(__dirname + "/docs/recipes.html", "utf8");
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
console.log("recipe pack calculator: all checks passed");
