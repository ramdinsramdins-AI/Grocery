// Language menu and translations for both pages. English text in the pages is the key: t("Add") looks it up in
// i18n/<code>.json (loaded only when that language is picked) and falls back to the English when a translation is
// missing. Recipes, ingredient names and tags have their own sections in the same file. Product names are not
// translated: they are the stores' own names.
(function () {
  // flags are drawn here because Windows shows flag emoji as two letters
  var F = {
    nz: '<rect width="30" height="20" fill="#012169"/><path d="M0 0l15 10M15 0L0 10" stroke="#fff" stroke-width="2.4"/><path d="M0 0l15 10M15 0L0 10" stroke="#C8102E" stroke-width="1"/><path d="M7.5 0v10M0 5h15" stroke="#fff" stroke-width="3.2"/><path d="M7.5 0v10M0 5h15" stroke="#C8102E" stroke-width="1.8"/><g fill="#C8102E" stroke="#fff" stroke-width=".5"><circle cx="23" cy="4" r="1.3"/><circle cx="20" cy="9" r="1.3"/><circle cx="26" cy="8.5" r="1.3"/><circle cx="23" cy="16" r="1.5"/></g>',
    cn: '<rect width="30" height="20" fill="#EE1C25"/><g fill="#FFFF00"><path d="M5 2.2l1.2 3.6h3.8l-3.1 2.2 1.2 3.6L5 9.4l-3.1 2.2 1.2-3.6L0 5.8h3.8z"/><circle cx="10.5" cy="2" r=".8"/><circle cx="12.3" cy="4" r=".8"/><circle cx="12.3" cy="6.8" r=".8"/><circle cx="10.5" cy="8.8" r=".8"/></g>',
    jp: '<rect width="30" height="20" fill="#fff"/><circle cx="15" cy="10" r="6" fill="#BC002D"/>',
    th: '<rect width="30" height="20" fill="#A51931"/><rect y="3.33" width="30" height="13.34" fill="#F4F5F8"/><rect y="6.67" width="30" height="6.66" fill="#2D2A4A"/>',
    in: '<rect width="30" height="20" fill="#138808"/><rect width="30" height="13.33" fill="#fff"/><rect width="30" height="6.67" fill="#FF9933"/><circle cx="15" cy="10" r="2.6" fill="none" stroke="#000080" stroke-width=".7"/><circle cx="15" cy="10" r=".6" fill="#000080"/>',
    mi: '<rect width="30" height="20" fill="#D40000"/><rect width="30" height="9" fill="#000"/><rect y="9" width="30" height="2" fill="#fff"/><path d="M3 10c0-4 8-4 8 0 0 2.5-4.5 2.5-4.5 0 0-1 1.6-1 1.6 0" fill="none" stroke="#fff" stroke-width="1.4"/>',
    ph: '<rect width="30" height="20" fill="#CE1126"/><rect width="30" height="10" fill="#0038A8"/><path d="M0 0l17.3 10L0 20z" fill="#fff"/><circle cx="6" cy="10" r="2.2" fill="#FCD116"/><g fill="#FCD116"><circle cx="2" cy="3" r=".8"/><circle cx="2" cy="17" r=".8"/><circle cx="13" cy="10" r=".8"/></g>',
    kr: '<rect width="30" height="20" fill="#fff"/><path d="M10 10a5 5 0 0 1 10 0z" fill="#CD2E3A"/><path d="M10 10a5 5 0 0 0 10 0z" fill="#0047A0"/><path d="M10 10a2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 1 5 0" fill="#CD2E3A"/><path d="M10 10a2.5 2.5 0 0 0 5 0z" fill="#0047A0"/><g stroke="#000" stroke-width=".9"><path d="M3.5 3l3 -1.5M4 4l3-1.5M4.5 5l3-1.5M22.5 14.5l3 1.5M23 13.5l3 1.5M23.5 12.5l3 1.5M22.5 5.5l3-1.5M23 6.5l3-1.5M3.5 15l3 1.5M4 14l3 1.5"/></g>',
    fr: '<rect width="30" height="20" fill="#EF4135"/><rect width="20" height="20" fill="#fff"/><rect width="10" height="20" fill="#0055A4"/>',
    de: '<rect width="30" height="20" fill="#FFCE00"/><rect width="30" height="13.33" fill="#DD0000"/><rect width="30" height="6.67" fill="#000"/>',
    ru: '<rect width="30" height="20" fill="#D52B1E"/><rect width="30" height="13.33" fill="#0039A6"/><rect width="30" height="6.67" fill="#fff"/>',
    es: '<rect width="30" height="20" fill="#AA151B"/><rect y="5" width="30" height="10" fill="#F1BF00"/>'
  };
  var LANGS = [
    {code: "en", flag: "nz", label: "English", locale: "en-NZ"},
    {code: "zh", flag: "cn", label: "中文 (Mandarin)", locale: "zh-CN"},
    {code: "ja", flag: "jp", label: "日本語 (Japanese)", locale: "ja-JP"},
    {code: "th", flag: "th", label: "ไทย (Thai)", locale: "th-TH"},
    {code: "hi", flag: "in", label: "हिन्दी (Hindi)", locale: "hi-IN"},
    {code: "mi", flag: "mi", label: "Te Reo Māori", locale: "mi-NZ"},
    {code: "fil", flag: "ph", label: "Filipino", locale: "fil-PH"},
    {code: "ko", flag: "kr", label: "한국어 (Korean)", locale: "ko-KR"},
    {code: "fr", flag: "fr", label: "Français (French)", locale: "fr-FR"},
    {code: "de", flag: "de", label: "Deutsch (German)", locale: "de-DE"},
    {code: "ru", flag: "ru", label: "Русский (Russian)", locale: "ru-RU"},
    {code: "es", flag: "es", label: "Español (Spanish)", locale: "es-ES"}
  ];
  var KEY = "shelfcheck-lang";
  var dict = {ui: {}, tags: {}, ingredients: {}, recipes: {}};
  var current = LANGS[0];
  var listeners = [];

  function flag(code) {
    return '<svg class="flag" viewBox="0 0 30 20" width="24" height="16" aria-hidden="true">' + F[code] + "</svg>";
  }
  function fill(s, vars) {
    return vars ? s.replace(/\{(\w+)\}/g, function (m, k) { return vars[k] != null ? vars[k] : m; }) : s;
  }
  // t(english, vars), e.g. the English "{n} recipes" with {n: 3}: the English text is the key
  function t(en, vars) { return fill(dict.ui[en] || en, vars); }
  // the same for HTML: the text is escaped, the values are inserted as they are (they must already be safe HTML)
  function html(en, vars) {
    return fill((dict.ui[en] || en).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }), vars);
  }

  // static text in the page: data-i18n (text), data-i18n-ph (placeholder), data-i18n-aria (aria-label)
  function applyStatic() {
    document.documentElement.lang = current.locale;
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      if (!el.dataset.en) el.dataset.en = el.textContent.trim();
      el.textContent = t(el.dataset.en);
    });
    document.querySelectorAll("[data-i18n-ph]").forEach(function (el) {
      if (!el.dataset.enPh) el.dataset.enPh = el.getAttribute("placeholder");
      el.setAttribute("placeholder", t(el.dataset.enPh));
    });
    document.querySelectorAll("[data-i18n-aria]").forEach(function (el) {
      if (!el.dataset.enAria) el.dataset.enAria = el.getAttribute("aria-label");
      el.setAttribute("aria-label", t(el.dataset.enAria));
    });
  }

  function renderMenu() {
    var box = document.getElementById("lang");
    if (!box) return;
    box.innerHTML = '<button type="button" class="langbtn" aria-haspopup="listbox" aria-expanded="false" aria-label="' +
      t("Language") + ": " + current.label + '">' + flag(current.flag) + "<span>" + current.label + '</span><span aria-hidden="true">▾</span></button>' +
      '<ul class="langlist" role="listbox" aria-label="' + t("Language") + '" hidden>' + LANGS.map(function (l) {
        return '<li role="option" aria-selected="' + (l.code === current.code) + '"><button type="button" data-lang="' + l.code + '">' +
          flag(l.flag) + "<span>" + l.label + "</span></button></li>";
      }).join("") + "</ul>";
  }
  function setOpen(open) {
    var b = document.querySelector("#lang .langbtn"), l = document.querySelector("#lang .langlist");
    if (!b || !l) return;
    b.setAttribute("aria-expanded", String(open)); l.hidden = !open;
    if (open) { var sel = l.querySelector('[aria-selected="true"] button'); if (sel) sel.focus(); }
  }

  function use(code) {
    var lang = LANGS.filter(function (l) { return l.code === code; })[0] || LANGS[0];
    var done = function (d) {
      dict = {ui: d.ui || {}, tags: d.tags || {}, ingredients: d.ingredients || {}, recipes: d.recipes || {}};
      current = lang;
      try { localStorage.setItem(KEY, lang.code); } catch (e) {}
      renderMenu(); applyStatic();
      listeners.forEach(function (f) { f(); });
    };
    if (lang.code === "en") return done({});
    fetch("i18n/" + lang.code + ".json", {cache: "no-cache"}).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(done).catch(function () { done({}); });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("#lang button") : null;
    if (!b) { setOpen(false); return; }
    if (b.classList.contains("langbtn")) { setOpen(b.getAttribute("aria-expanded") !== "true"); return; }
    if (b.dataset.lang) { setOpen(false); use(b.dataset.lang); }
  });
  document.addEventListener("keydown", function (e) {
    var b = document.querySelector("#lang .langbtn");
    if (e.key === "Escape" && b && b.getAttribute("aria-expanded") === "true") { setOpen(false); b.focus(); }
  });

  var css = document.createElement("style");
  css.textContent = "#lang{position:relative}" +
    ".langbtn{display:flex;align-items:center;gap:8px;font:inherit;font-size:13px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:6px 10px;cursor:pointer}" +
    ".langlist{position:absolute;right:0;top:calc(100% + 4px);z-index:20;margin:0;padding:4px;list-style:none;background:var(--surface);border:1px solid var(--line);border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,.18);min-width:220px;max-height:70vh;overflow:auto}" +
    ".langlist button{display:flex;align-items:center;gap:10px;width:100%;font:inherit;font-size:14px;background:none;border:0;color:var(--ink);padding:8px 10px;border-radius:4px;cursor:pointer;text-align:left}" +
    ".langlist button:hover,.langlist [aria-selected=true] button{background:var(--soft)}" +
    ".flag{flex:0 0 auto;border-radius:2px;box-shadow:0 0 0 1px rgba(0,0,0,.18)}" +
    ".hside{display:flex;flex-direction:column;align-items:flex-end;gap:8px}@media (max-width:600px){.hside{align-items:flex-start}.langlist{left:0;right:auto}}";
  document.head.appendChild(css);

  window.I18N = {
    t: t,
    html: html,
    locale: function () {   // for dates; a browser without that language's formats (often Māori) gets the NZ English ones
      try { if (Intl.DateTimeFormat.supportedLocalesOf([current.locale]).length) return current.locale; } catch (e) {}
      return "en-NZ";
    },
    code: function () { return current.code; },
    tag: function (tag) { return dict.tags[tag] || tag; },
    ingredient: function (id, en) { return dict.ingredients[id] || en; },
    recipe: function (r) {   // {name, blurb, method[], notes{index: text}} with English for anything not translated
      var x = dict.recipes[r.id] || {};
      return {name: x.name || r.name, blurb: x.blurb || r.blurb,
              method: x.method && x.method.length === r.method.length ? x.method : r.method, notes: x.notes || {}};
    },
    onChange: function (f) { listeners.push(f); },
    start: function () {
      var saved = null;
      try { saved = localStorage.getItem(KEY); } catch (e) {}
      renderMenu(); applyStatic();
      if (saved && saved !== "en") use(saved);
    }
  };
})();
