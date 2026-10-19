// Checks how docs/account.js settles a list that differs between this device and the account, and how each page
// combines two lists. Run: node test_account.js
const fs = require("fs"), assert = require("assert"), vm = require("vm");
const read = (f) => fs.readFileSync(__dirname + "/docs/" + f, "utf8").replace(/\r\n/g, "\n");   // Git on Windows checks out CRLF

// account.js with no Firebase settings: it only defines window.Account
const win = {};
vm.runInNewContext(read("account.js"), {window: win, location: {hostname: "example.org", search: ""}});
const decide = win.Account.decide;
assert.ok(decide, "Account.decide exists without Firebase settings");

// the list a page hands to Account.sync (its get, set and merge)
function pageSync(file, key) {
  const src = read(file).match(/<script>([\s\S]*)<\/script>/)[1];
  const block = src.match(new RegExp('if\\(window\\.Account\\)Account\\.sync\\("' + key + '",\\{[\\s\\S]*?\\n\\}\\);'))[0];
  let page = null;
  vm.runInNewContext(block, {window: {Account: 1}, Account: {sync: (k, p) => { page = p; }}});
  return page;
}
const J = JSON.stringify;
// objects from the sandbox have its own Object, so compare them as JSON (which also checks the order of keys)
const same = (a, b) => assert.strictEqual(J(a), J(b));
// the product page's merge: every item at the larger quantity, the account's cost per stop
const live = pageSync("index.html", "live");
same(live.merge({list: {a: 1, b: 2}, stop: 4}, {list: {b: 3, c: 1}, stop: 6}), {list: {a: 1, b: 3, c: 1}, stop: 6});
same(live.merge({list: {a: 2}, stop: 4}, {list: {}}), {list: {a: 2}, stop: 4});

const here = J({list: {a: 1}, stop: 4}), acct = J({list: {b: 1}, stop: 4});
// nothing in the account yet: this device's list goes up
same(decide(here, null, null, live.merge), {apply: null, upload: here});
// the same on both sides: nothing to do
same(decide(here, here, null, live.merge), {apply: null, upload: null});
// only the account changed since this device last saw it (e.g. an item removed on the phone): show the account's
same(decide(here, acct, here, live.merge), {apply: acct, upload: null});
// only this device changed (e.g. edited while offline): save it to the account
same(decide(here, acct, acct, live.merge), {apply: null, upload: here});
// first sign-in on this device, or both changed: keep what is in either, on both sides
const both = J({list: {a: 1, b: 1}, stop: 4});
same(decide(here, acct, null, live.merge), {apply: both, upload: both});
same(decide(here, acct, J({list: {}, stop: 4}), live.merge), {apply: both, upload: both});
// an empty list here on first sign-in takes the account's list and leaves the account alone
same(decide(J({list: {}, stop: 4}), acct, null, live.merge), {apply: acct, upload: null});

// the recipe page's merge: every recipe at the larger number of servings, the account's ticks win
const recipes = pageSync("recipes.html", "recipes");
same(recipes.merge({sel: {pad: 2, soup: 4}, have: {salt: true, rice: true}, stop: 4}, {sel: {soup: 6, curry: 4}, have: {salt: false}, stop: 3}),
     {sel: {pad: 2, soup: 6, curry: 4}, have: {salt: false, rice: true}, stop: 3});

console.log("account sync: all checks passed");
