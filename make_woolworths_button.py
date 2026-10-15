"""Builds woolworths-button.html: a page with a "Collect Woolworths prices" button to drag onto the bookmarks bar.
The button runs collect-woolworths.js on woolworths.co.nz. Run again after changing that file:
    python make_woolworths_button.py
"""
import html
import pathlib
import urllib.parse

ROOT = pathlib.Path(__file__).parent
src = (ROOT / "collect-woolworths.js").read_text(encoding="utf-8")
code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("//"))
bookmarklet = "javascript:" + urllib.parse.quote(code, safe="()[]{};:,.=<>!&|?+-*/'\"$` _")

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Woolworths price button</title>
<style>
  body {{ font: 17px/1.5 system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; color: #1b1b1b; background: #fafaf7; }}
  h1 {{ font-size: 26px; margin-bottom: 4px; }}
  .btn {{ display: inline-block; margin: 18px 0; padding: 14px 22px; border-radius: 10px; background: #1d5c2e; color: #fff;
         font-weight: 700; text-decoration: none; cursor: grab; }}
  ol li {{ margin-bottom: 10px; }}
  .note {{ color: #555; font-size: 15px; }}
  code {{ background: #eee; padding: 1px 5px; border-radius: 4px; }}
</style>
</head>
<body>
<h1>Woolworths price button</h1>
<p>Shelf Check uses this button to collect Woolworths prices once a week.</p>

<h2>Set it up (once)</h2>
<ol>
  <li>Show your bookmarks bar: press <b>Ctrl + Shift + B</b>.</li>
  <li>Drag this green button up onto the bookmarks bar:<br>
      <a class="btn" href="{html.escape(bookmarklet, quote=True)}" onclick="alert('Drag this button onto your bookmarks bar instead of clicking it here.'); return false;">Collect Woolworths prices</a></li>
</ol>

<h2>Use it (about once a week)</h2>
<ol>
  <li>Go to <b>www.woolworths.co.nz</b> (any page).</li>
  <li>Click <b>Collect Woolworths prices</b> on your bookmarks bar. A green bar appears at the top of the page and shows progress.</li>
  <li>Leave the tab open for 10 to 15 minutes. When it says <b>done</b>, the prices are saved in your Downloads folder.</li>
  <li>That's it. Within 10 minutes your PC sends them to GitHub, shows a message in the corner of your screen,
      and moves the old price files to the Recycle Bin. Your website uses the new prices at its next update (6am, 12pm or 6pm).</li>
</ol>

<p class="note">If clicking the button does nothing on the Woolworths site, use the old way instead: open DevTools &gt; Sources &gt; Snippets
and run <code>collect-woolworths.js</code>. Your PC still uploads the file for you.</p>
</body>
</html>
"""
(ROOT / "woolworths-button.html").write_text(page, encoding="utf-8")
print(f"woolworths-button.html written ({len(bookmarklet)} characters in the button)")
