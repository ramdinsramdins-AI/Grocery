// Accounts: shoppers can sign in with an email and a password so their shopping list (index.html) and chosen recipes
// (recipes.html) follow them to every device where they sign in. Google Firebase checks the passwords and stores the
// lists: one Firestore document per person, users/<their id>, that only they can read or write (firestore.rules).
// Each page can also keep named saved lists ("My saved lists"), on the device and, when signed in, in the account.
// account-config.js holds the Firebase project's settings. While it is empty there is no account button and the pages
// save to this device only, as before. Firebase's code is fetched only when someone opens the account box or is signed in.
(function () {
  var SDK = "https://www.gstatic.com/firebasejs/12.19.0/";
  var FLAG = "shelfcheck-account";        // "1" while someone is signed in on this device, so Firebase loads straight away
  var BASE = "shelfcheck-account-base";   // {uid, live, recipes, liveSaved, recipesSaved}: each as the account last held it
  var DELAY = 800;                        // ms after the last change before it is saved to the account
  var MAXSAVED = 30;                      // named saved lists per page

  // What to do when this device's list and the account's list differ. Lists are JSON text; `base` is the account's list
  // the last time this device was in step with it (null on the first sign-in here). Returns the list to show on this
  // device (apply) and the list to save to the account (upload); null leaves that side as it is.
  function decide(local, remote, base, merge) {
    if (remote == null) return {apply: null, upload: local};
    if (local === remote) return {apply: null, upload: null};
    if (base != null && local === base) return {apply: remote, upload: null};   // only the account changed
    if (base != null && remote === base) return {apply: null, upload: local};   // only this device changed
    var both = JSON.stringify(merge(JSON.parse(local), JSON.parse(remote)));    // both changed: keep what is in either
    return {apply: both === local ? null : both, upload: both === remote ? null : both};
  }

  // Two copies of a page's saved lists, [{id, name, at, data}], where a deleted one is kept as {id, at, gone: 1}: the newer
  // of each wins, so a list deleted on one device stays deleted. Newest first; deletions are forgotten after 90 days.
  function mergeSaved(a, b) {
    var by = {};
    a.concat(b).forEach(function (s) { var o = by[s.id]; if (!o || s.at >= o.at) by[s.id] = s; });
    return tidy(Object.keys(by).map(function (id) { return by[id]; }));
  }
  function tidy(list) {
    var old = Date.now() - 90 * 864e5;
    return list.filter(function (s) { return !s.gone || s.at > old; }).sort(function (x, y) { return y.at - x.at || (x.id < y.id ? -1 : 1); });
  }

  var pages = {}, lists = {}, user = null, fb = null, loading = null, unwatch = null, timer = null, ready = false;
  var inStep = false, applying = false, saveState = "";   // saveState: "", "saving", "saved" or "failed"
  window.Account = {
    // a page's list: get() returns it, set(data) shows it and saves it on this device, merge(here, account) combines two
    sync: function (key, page) { pages[key] = page; },
    // the page calls this after every change to its list
    changed: function () { if (!applying && user && inStep) schedule(); },
    // the page's saved lists, drawn in its #lists: count(data) is how many things a list holds, summary(n) says so in words
    lists: function (key, page) {
      lists[key] = page;
      pages[key + "Saved"] = {get: function () { return savedAll(key); }, set: function (a) { setSaved(key, Array.isArray(a) ? a : []); }, merge: mergeSaved};
      if (ready) drawLists();
    },
    decide: decide,
    mergeSaved: mergeSaved
  };

  var host = location.hostname, onPC = host === "localhost" || host === "127.0.0.1" || host === "[::1]";
  // http://127.0.0.1:8000/?emulator uses Firebase's emulators on this PC instead of the real project (see HANDOVER.md)
  var emulator = onPC && /[?&]emulator\b/.test(location.search);
  // account-config.js holds `const firebaseConfig = {...}` as copied from the Firebase console (anywhere in that file)
  var config = emulator ? {apiKey: "demo-key", authDomain: "demo-shelfcheck.firebaseapp.com", projectId: "demo-shelfcheck"}
                        : typeof firebaseConfig === "undefined" ? null : firebaseConfig;
  if (!config || !config.apiKey || !config.projectId) return;   // accounts not set up: no button

  var T = I18N.t, TH = I18N.html;   // T(english, vars) gives the chosen language; TH does the same for HTML
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function write(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }
  function baseFor(key) {
    try { var b = JSON.parse(read(BASE) || "null"); return b && b.uid === user.uid && typeof b[key] === "string" ? b[key] : null; } catch (e) { return null; }
  }
  function setBase(key, s) {
    var b = null;
    try { b = JSON.parse(read(BASE) || "null"); } catch (e) {}
    if (!b || b.uid !== user.uid) b = {uid: user.uid};
    b[key] = s; write(BASE, JSON.stringify(b));
  }
  function savedAll(key) {
    try { var a = JSON.parse(read("shelfcheck-" + key + "-saved") || "[]"); return Array.isArray(a) ? a : []; } catch (e) { return []; }
  }
  function savedShown(key) { return savedAll(key).filter(function (s) { return !s.gone; }); }
  function setSaved(key, a) {
    write("shelfcheck-" + key + "-saved", JSON.stringify(a));
    drawLists();
    if (dlg && dlg.open && view === "lists") drawBox();
  }

  function load() {
    if (!loading) {
      loading = Promise.all(["app", "auth", "firestore"].map(function (m) { return import(SDK + "firebase-" + m + ".js"); })).then(function (m) {
        var app = m[0].initializeApp(config), auth = m[1].getAuth(app), db = m[2].getFirestore(app);
        if (emulator) { m[1].connectAuthEmulator(auth, "http://127.0.0.1:9099", {disableWarnings: true}); m[2].connectFirestoreEmulator(db, "127.0.0.1", 8080); }
        fb = {a: m[1], f: m[2], auth: auth, db: db};
        m[1].onAuthStateChanged(auth, signedIn);
        return fb;
      });
      loading.catch(function () { loading = null; });   // try again next time the box is opened
    }
    return loading;
  }
  function ref() { return fb.f.doc(fb.db, "users", user.uid); }

  // signed in or out (also on page load). While signed in, the account's document is watched: the first reading
  // settles any difference with this device (decide), later ones are changes made on another device.
  function signedIn(u) {
    if (unwatch) { unwatch(); unwatch = null; }
    clearTimeout(timer); timer = null;
    user = u; inStep = false; saveState = "";
    write(FLAG, u ? "1" : null);
    if (!u) { write(BASE, null); draw(); return; }
    unwatch = fb.f.onSnapshot(ref(), {includeMetadataChanges: true}, function (snap) {
      // skip this device's own unsent saves, and an offline first reading that may be out of date
      if (snap.metadata.hasPendingWrites || (!inStep && snap.metadata.fromCache)) return;
      var data = snap.exists() ? snap.data() : {}, up = {};
      Object.keys(pages).forEach(function (key) { var s = fromAccount(key, typeof data[key] === "string" ? data[key] : null); if (s) up[key] = s; });
      inStep = true;
      if (Object.keys(up).length) upload(up);
    }, function () { saveState = "failed"; drawSync(); });
    draw();
  }
  // returns the text to save to the account, if any
  function fromAccount(key, remote) {
    var page = pages[key], here = JSON.stringify(page.get());
    if (!inStep) {
      var d = decide(here, remote, baseFor(key), page.merge);
      if (d.apply) show(key, d.apply);
      if (!d.upload) setBase(key, remote);
      return d.upload;
    }
    if (timer || remote == null) return null;   // a change made here is about to be saved over it
    if (remote !== here) show(key, remote);
    setBase(key, remote);
    return null;
  }
  function show(key, s) {
    applying = true;
    try { pages[key].set(JSON.parse(s)); } finally { applying = false; }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(flush, DELAY);
    saveState = "saving"; drawSync();
  }
  function flush() {
    if (!timer) return Promise.resolve();
    clearTimeout(timer); timer = null;
    var up = {};
    Object.keys(pages).forEach(function (key) { var s = JSON.stringify(pages[key].get()); if (s !== baseFor(key)) up[key] = s; });
    return upload(up);
  }
  // saves {key: text} to the account in one go (only what changed since the account last had it)
  function upload(up) {
    var uid = user.uid, data = {updated: fb.f.serverTimestamp()}, keys = Object.keys(up);
    if (!keys.length) { saveState = "saved"; drawSync(); return Promise.resolve(); }
    keys.forEach(function (k) { data[k] = up[k]; });
    saveState = "saving"; drawSync();
    return fb.f.setDoc(ref(), data, {merge: true}).then(function () {
      if (user && user.uid === uid) { keys.forEach(function (k) { setBase(k, up[k]); }); saveState = "saved"; drawSync(); }
    }, function () { saveState = "failed"; drawSync(); });
  }
  addEventListener("pagehide", flush);

  // ---- the account button, the box (account or saved lists) and the line under the page's list ----
  var ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg>';
  var TICK = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>';
  var dlg = null, view = "account", mode = "in", msg = {text: "", cls: ""}, email = "", deleting = false;
  function signedInHere() { return !!user || (!fb && read(FLAG) === "1"); }   // before Firebase loads, trust the flag

  function drawButton() {
    var box = document.getElementById("account");
    if (!box) return;
    var label = user || (!fb && read(FLAG) === "1") ? T("My account") : T("Sign in");
    var b = box.querySelector("button");
    if (!b) { box.innerHTML = '<button type="button" class="acctbtn" aria-haspopup="dialog">' + ICON + "<span></span></button>"; b = box.querySelector("button"); }
    b.querySelector("span").textContent = label;
  }
  function draw() { drawButton(); drawLists(); if (dlg && dlg.open) drawBox(); }
  function syncText() {
    return saveState === "saving" ? T("Saving to your account...") : saveState === "saved" ? T("Saved to your account.") :
      saveState === "failed" ? T("Could not save to your account. Your list is still saved on this device.") : "";
  }
  function drawSync() { var el = dlg && dlg.querySelector("#acct-sync"); if (el) el.textContent = syncText(); drawLists(); }

  // under "Your list": whether it is saved to the account or only here, and the "My saved lists" button
  function drawLists() {
    var box = document.getElementById("lists"), key = Object.keys(lists)[0];
    if (!box || !key || !ready) return;
    if (!box.firstChild) {
      box.innerHTML = '<p class="lists-st" role="status"></p><button type="button" class="btn in" data-acct="lists"></button>';
    }
    var st = box.firstChild, on = signedInHere(), n = savedShown(key).length;
    st.className = "lists-st" + (!on ? "" : saveState === "failed" ? " bad" : saveState === "saving" ? "" : " ok");
    st.innerHTML = !on ? esc(T("Saved on this device only.")) + ' <button type="button" class="acct-link" data-acct="account">' + esc(T("Sign in to keep it on all your devices")) + "</button>"
      : saveState === "saving" ? esc(T("Saving to your account...")) : saveState === "failed" ? esc(T("Could not save to your account. Your list is still saved on this device."))
      : TICK + esc(T("Saved to your account."));
    box.lastChild.textContent = T("My saved lists") + (n ? " (" + n + ")" : "");
  }
  function when(at) { try { return new Intl.DateTimeFormat(I18N.locale(), {dateStyle: "medium"}).format(new Date(at)); } catch (e) { return ""; } }
  function say(text, cls) { msg = {text: text || "", cls: cls || ""}; var el = dlg && dlg.querySelector("#acct-msg"); if (el) { el.textContent = msg.text; el.className = "acct-msg " + msg.cls; } }

  function drawBox() {
    var em = dlg.querySelector("#acct-email");
    if (em) email = em.value;
    var h = '<div class="acct-in"><div class="acct-top"><h2 id="acct-h">' + esc(view === "lists" ? T("My saved lists") : T("Your account")) +
      '</h2><button type="button" class="acct-x" data-act="close" aria-label="' + esc(T("Close")) + '">&times;</button></div>';
    if (view === "lists") {
      var key = Object.keys(lists)[0], page = lists[key], items = savedShown(key);
      h += '<form id="acct-form" data-form="save" novalidate><label class="f" for="acct-name">' + esc(T("Save the list you have now as")) +
        '<input type="text" id="acct-name" maxlength="40" autocomplete="off" placeholder="' + esc(T("For example: Weekly shop")) + '"></label>' +
        '<button type="submit" class="btn">' + esc(T("Save")) + "</button></form>" +
        '<p class="note small">' + esc(T("Opening a saved list replaces the list you have now. Save it first if you want to keep it.")) + "</p>" +
        (items.length ? '<ul class="saved">' + items.map(function (it) {
          return "<li><div><b>" + esc(it.name) + "</b><span>" + esc(page.summary(page.count(it.data))) + " · " + esc(when(it.at)) + "</span></div>" +
            '<button type="button" class="btn in" data-act="open" data-id="' + esc(it.id) + '">' + esc(T("Open")) + "</button>" +
            '<button type="button" class="acct-link danger" data-act="del" data-id="' + esc(it.id) + '">' + esc(T("Delete")) + "</button></li>";
        }).join("") + "</ul>" : '<p class="note">' + esc(T("No saved lists yet.")) + "</p>") +
        (signedInHere() ? "" : '<p class="note small">' + esc(T("Saved lists are kept on this device only. Sign in to keep them on all your devices.")) +
          ' <button type="button" class="acct-link" data-act="to-account">' + esc(T("Sign in")) + "</button></p>");
    } else if (!fb) h += '<p class="note">' + esc(T("Loading...")) + "</p>";
    else if (user && deleting) {
      h += '<p>' + esc(T("This deletes your account and the lists saved in it. Type your password to confirm.")) + '</p><form id="acct-form" data-form="delete" novalidate>' +
        '<label class="f" for="acct-pw">' + esc(T("Password")) + '<input type="password" id="acct-pw" autocomplete="current-password" required></label>' +
        '<div class="acct-row"><button type="submit" class="btn danger">' + esc(T("Delete my account")) + '</button><button type="button" class="btn in" data-act="cancel">' + esc(T("Cancel")) + "</button></div></form>";
    } else if (user) {
      h += "<p>" + TH("Signed in as {email}", {email: "<b>" + esc(user.email) + "</b>"}) + "</p>" +
        '<p class="note">' + esc(T("Your shopping list and recipes save to your account, so they show on any device where you sign in.")) + "</p>" +
        '<p id="acct-sync" class="acct-sync" role="status">' + esc(syncText()) + "</p>" +
        '<div class="acct-row"><button type="button" class="btn" data-act="out">' + esc(T("Sign out")) + "</button></div>" +
        '<div class="acct-row"><button type="button" class="acct-link" data-act="change">' + esc(T("Change my password")) + "</button>" +
        '<button type="button" class="acct-link danger" data-act="delete">' + esc(T("Delete my account")) + "</button></div>";
    } else {
      var isNew = mode === "new";
      h += '<p class="note">' + esc(T("Sign in to keep your shopping list and recipes on all your devices. Without an account they are saved on this device only.")) + "</p>" +
        '<div class="acct-tabs"><button type="button" data-act="mode-in" aria-pressed="' + !isNew + '">' + esc(T("Sign in")) + '</button><button type="button" data-act="mode-new" aria-pressed="' + isNew + '">' +
        esc(T("Create account")) + "</button></div>" +
        '<form id="acct-form" data-form="' + mode + '" novalidate><label class="f" for="acct-email">' + esc(T("Email")) +
        '<input type="email" id="acct-email" autocomplete="username" inputmode="email" required value="' + esc(email) + '"></label>' +
        '<label class="f" for="acct-pw">' + esc(T("Password")) + '<input type="password" id="acct-pw" autocomplete="' + (isNew ? "new-password" : "current-password") + '" required' +
        (isNew ? ' minlength="6" aria-describedby="acct-pwhint"' : "") + "></label>" +
        (isNew ? '<p class="note small" id="acct-pwhint">' + esc(T("At least 6 characters.")) + "</p>" : "") +
        '<label class="acct-show"><input type="checkbox" id="acct-show"> ' + esc(T("Show password")) + "</label>" +
        '<button type="submit" class="btn">' + esc(isNew ? T("Create account") : T("Sign in")) + "</button>" +
        (isNew ? "" : '<button type="button" class="acct-link" data-act="forgot">' + esc(T("Forgot your password?")) + "</button>") + "</form>" +
        '<p class="note small">' + esc(T("Your email address and lists are stored with Google Firebase for this site. Other shoppers cannot see them.")) + "</p>";
    }
    h += '<p id="acct-msg" class="acct-msg ' + msg.cls + '" role="alert">' + esc(msg.text) + "</p></div>";
    dlg.innerHTML = h;
  }

  function errText(e) {
    var c = (e && e.code) || "";
    if (/invalid-email|missing-email/.test(c)) return T("That email address does not look right.");
    if (/invalid-credential|wrong-password|user-not-found|invalid-login-credentials|user-mismatch/.test(c)) return T("Wrong email or password.");
    if (/email-already-in-use/.test(c)) return T("There is already an account with that email. Try signing in instead.");
    if (/weak-password|password-does-not-meet-requirements/.test(c)) return T("Choose a password with at least 6 characters.");
    if (/too-many-requests/.test(c)) return T("Too many tries. Wait a few minutes, then try again.");
    if (/operation-not-allowed|configuration-not-found/.test(c)) return T("Email sign-in is not switched on for this site yet.");
    if (/network-request-failed|unavailable/.test(c) || !c) return T("Could not connect. Check your internet connection and try again.");
    return T("Something went wrong. Please try again.");
  }
  function lang() { var c = I18N.code(); return c === "zh" ? "zh-CN" : c; }   // for Firebase's own emails
  function busy(on) { dlg.querySelectorAll("button, input").forEach(function (el) { el.disabled = on; }); }
  function after(p, done) {
    busy(true); say("");
    p.then(function (x) { busy(false); if (done) done(x); }, function (e) { busy(false); say(errText(e), "bad"); });
  }

  function open(which) {
    view = which;
    if (!dlg) {
      dlg = document.createElement("dialog");
      dlg.className = "acct";
      dlg.setAttribute("aria-labelledby", "acct-h");
      document.body.appendChild(dlg);
      dlg.addEventListener("click", onClick);
      dlg.addEventListener("submit", onSubmit);
      dlg.addEventListener("change", function (e) { if (e.target.id === "acct-show") { var p = dlg.querySelector("#acct-pw"); if (p) p.type = e.target.checked ? "text" : "password"; } });
      dlg.addEventListener("close", function () { deleting = false; msg = {text: "", cls: ""}; });
    }
    drawBox();
    if (!dlg.open) dlg.showModal();
    focusFirst();
    if (!fb && view === "account") load().then(function () { if (view === "account") { drawBox(); focusFirst(); } }, function () { say(T("Could not connect. Check your internet connection and try again."), "bad"); });
  }
  function focusFirst() { var f = dlg.querySelector("#acct-email, #acct-pw, #acct-name"); if (f) f.focus(); }

  function saveAs(name) {
    var key = Object.keys(lists)[0], data = JSON.parse(JSON.stringify(pages[key].get())), all = savedAll(key);
    if (!lists[key].count(data)) { say(T("Your list is empty, so there is nothing to save."), "bad"); return; }
    var same = all.filter(function (it) { return !it.gone && it.name.toLowerCase() === name.toLowerCase(); })[0];
    if (!same && savedShown(key).length >= MAXSAVED) { say(T("You can keep up to {n} saved lists. Delete one to save another.", {n: MAXSAVED}), "bad"); return; }
    var now = Date.now(), id = same ? same.id : now.toString(36) + Math.random().toString(36).slice(2, 6);
    setSaved(key, tidy(all.filter(function (it) { return it.id !== id; }).concat([{id: id, name: name, at: now, data: data}])));
    savedChanged();
    say(T('Saved "{name}".', {name: name}), "ok");
  }
  function savedChanged() { if (user && inStep) schedule(); }

  function onClick(e) {
    if (e.target === dlg) { dlg.close(); return; }   // the dimmed area around the box
    var b = e.target.closest("[data-act]");
    if (!b) return;
    var act = b.dataset.act;
    if (act === "close") dlg.close();
    else if (act === "mode-in" || act === "mode-new") { mode = act.slice(5); say(""); drawBox(); focusFirst(); }
    else if (act === "to-account") { say(""); open("account"); }
    else if (act === "open" || act === "del") {
      var key = Object.keys(lists)[0], it = savedShown(key).filter(function (x) { return x.id === b.dataset.id; })[0];
      if (!it) return;
      if (act === "open") {
        pages[key].set(JSON.parse(JSON.stringify(it.data)));   // the page saves it as its list (and to the account)
        say(T('Opened "{name}".', {name: it.name}), "ok");
      } else if (confirm(T('Delete "{name}"?', {name: it.name}))) {
        setSaved(key, tidy(savedAll(key).map(function (x) { return x.id === it.id ? {id: x.id, at: Date.now(), gone: 1} : x; })));
        savedChanged();
        say(T('Deleted "{name}".', {name: it.name}), "ok");
      }
    }
    else if (act === "forgot") {
      var em = dlg.querySelector("#acct-email").value.trim();
      if (!em) { say(T("Type your email address."), "bad"); return; }
      fb.auth.languageCode = lang();
      after(fb.a.sendPasswordResetEmail(fb.auth, em), function () {
        say(T("If {email} has an account, a link to set a new password is on its way. Check your spam folder if it does not arrive.", {email: em}), "ok");
      });
    } else if (act === "change") {
      fb.auth.languageCode = lang();
      after(fb.a.sendPasswordResetEmail(fb.auth, user.email), function () {
        say(T("A link to set a new password is on its way to {email}. Check your spam folder if it does not arrive.", {email: user.email}), "ok");
      });
    } else if (act === "out") {
      after(flush().then(function () { return fb.a.signOut(fb.auth); }), function () { say(T("Signed out. The list on this device stays here."), "ok"); });
    } else if (act === "delete") { deleting = true; say(""); drawBox(); focusFirst(); }
    else if (act === "cancel") { deleting = false; say(""); drawBox(); }
  }

  function onSubmit(e) {
    e.preventDefault();
    var form = e.target.dataset.form;
    if (form === "save") {
      var name = dlg.querySelector("#acct-name").value.trim().replace(/\s+/g, " ");
      if (!name) say(T("Type a name for the list."), "bad"); else saveAs(name);
      return;
    }
    var pw = dlg.querySelector("#acct-pw").value;
    if (form === "delete") {
      if (!pw) { say(T("Type your password."), "bad"); return; }
      var u = user;
      after(fb.a.reauthenticateWithCredential(u, fb.a.EmailAuthProvider.credential(u.email, pw)).then(function () {
        if (unwatch) { unwatch(); unwatch = null; }
        clearTimeout(timer); timer = null;
        return fb.f.deleteDoc(ref()).then(function () { return fb.a.deleteUser(u); })
          .catch(function (e) { if (user) signedIn(user); throw e; });   // still signed in: watch the account again
      }), function () { deleting = false; say(T("Your account and the lists saved in it are deleted. The list on this device stays here."), "ok"); });
      return;
    }
    var em = dlg.querySelector("#acct-email").value.trim();
    if (!em) { say(T("Type your email address."), "bad"); return; }
    if (!pw) { say(T("Type your password."), "bad"); return; }
    if (form === "new" && pw.length < 6) { say(T("Choose a password with at least 6 characters."), "bad"); return; }
    email = em;
    after(form === "new" ? fb.a.createUserWithEmailAndPassword(fb.auth, em, pw) : fb.a.signInWithEmailAndPassword(fb.auth, em, pw));
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest(".acctbtn, [data-acct]") : null;
    if (b) open(b.dataset.acct || "account");
  });
  I18N.onChange(draw);

  var css = document.createElement("style");
  css.textContent = ".acctbtn{display:flex;align-items:center;gap:6px;font:inherit;font-size:13px;font-weight:600;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:6px 10px;cursor:pointer}" +
    "dialog.acct{width:min(420px,calc(100vw - 32px));max-height:calc(100vh - 32px);max-height:calc(100dvh - 32px);overflow:auto;padding:0;background:var(--surface);color:var(--ink);border:2px solid var(--ink);border-radius:6px}" +
    "dialog.acct::backdrop{background:rgba(0,0,0,.5)}" +
    ".acct-in{padding:18px 20px 20px}.acct-top{display:flex;justify-content:space-between;align-items:center;gap:12px}" +
    ".acct h2{font-family:var(--f-display);font-size:26px;text-transform:uppercase;margin:0;letter-spacing:.02em}" +
    ".acct-x{font:inherit;font-size:26px;line-height:1;background:none;border:0;color:var(--ink);cursor:pointer;padding:2px 8px;border-radius:4px}" +
    ".acct p{margin:12px 0 0;font-size:14px;overflow-wrap:anywhere}.acct .note{color:var(--muted)}.acct .small{font-size:12.5px}" +
    ".acct-tabs{display:flex;margin-top:14px;border:1px solid var(--line);border-radius:4px;overflow:hidden}" +
    ".acct-tabs button{flex:1;font:inherit;font-size:14px;font-weight:600;padding:9px 6px;background:var(--surface);color:var(--ink);border:0;cursor:pointer}" +
    ".acct-tabs [aria-pressed=true]{background:var(--ink);color:var(--bg)}" +
    ".acct form{display:flex;flex-direction:column;gap:12px;margin-top:14px}.acct form p{margin:-6px 0 0}" +
    ".acct .f{display:flex;flex-direction:column;gap:4px;font-size:13px;font-weight:600}" +
    ".acct .f input{font:inherit;font-size:16px;font-weight:400;color:var(--ink);background:var(--surface);border:1px solid var(--line);padding:10px 12px;border-radius:4px;width:100%}" +
    ".acct-show{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--muted);cursor:pointer}.acct-show input{width:18px;height:18px;accent-color:var(--ink)}" +
    ".acct .btn{padding:10px 16px}.acct .btn.danger{background:var(--warn);color:var(--surface)}" +
    ".acct-row{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:14px}" +
    ".acct-link{font:inherit;font-size:13px;font-weight:600;background:none;border:0;padding:4px 0;color:var(--ink);text-decoration:underline;cursor:pointer;align-self:flex-start}" +
    ".acct-link.danger{color:var(--warn)}.acct-sync{font-family:var(--f-mono);font-size:12px!important;color:var(--muted)}.acct-sync:empty,.acct-msg:empty{display:none}" +
    ".acct-msg.bad{color:var(--warn);font-weight:600}.acct-msg.ok{color:var(--good);font-weight:600}" +
    ".acct button:disabled{opacity:.6;cursor:wait}" +
    ".lists{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;justify-content:space-between;margin-top:-6px}.lists:empty{display:none}" +
    ".lists-st{margin:0;font-size:13px;color:var(--muted);display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px}.lists-st.ok{color:var(--good);font-weight:600}.lists-st.bad{color:var(--warn)}" +
    ".lists-st .acct-link{padding:0}.lists .btn{font-size:13px;padding:6px 12px}" +
    ".acct .saved{list-style:none;margin:16px 0 0;padding:0}" +
    ".acct .saved li{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px 12px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}" +
    ".acct .saved b{display:block;overflow-wrap:anywhere}.acct .saved span{font-size:12.5px;color:var(--muted)}.acct .saved .btn{padding:6px 12px}" +
    ".acct .saved .acct-link{align-self:center}";
  document.head.appendChild(css);

  ready = true;
  drawButton(); drawLists();
  if (read(FLAG) === "1") load().catch(function () {});
})();
