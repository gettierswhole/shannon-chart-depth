# Builds the two test layouts (Trim and Plain) under test/ from the built public page.
# They are the same page and the same live files, restyled: titles-only notices, folded extras, a short footer.
# Usage: python3 tools/build_tests.py index.html .
import sys, os, re

src, out = sys.argv[1], sys.argv[2]
h = open(src).read()

TRIM_CSS = r'''
.testbar { max-width: 960px; margin: 0 auto; padding: 10px 0 0; font-size: 0.85rem; color: var(--muted); }
.testbar b { color: var(--warn); }
.masthead { padding-block: 16px 4px; }
.sub { font-size: 0.88rem; }
#sun-bar, #sun-note, #trip > .fine, #food-asof { display: none !important; }
.notice-list { gap: 8px; }
.notice-list li:not(.urgent) > span:not(.ended-tag):not(.ended-note) { display: none; }
.fold { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; border-top: 1px solid var(--line); }
.fold + .fold { margin-top: 0; }
.fold > summary { font-weight: 600; min-height: 24px; }
.fold[open] > summary { margin-bottom: 12px; }
.fold > .panel, .fold > section { border: 0; padding: 0; background: none; margin: 0; }
.fold .sights-section, .fold .depth-section { border-top: 0; padding-top: 0; margin-top: 0; }
.fold .credits { margin-top: 0; }
.depth-section { gap: 12px; }
.short-foot { font-size: 0.8rem; color: var(--muted); margin: 0; padding: 0 4px; }
@media (max-width: 560px) {
  .reaches { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .reaches button { padding: 10px 12px; font-size: 0.92rem; }
  .reaches button .st-level { font-size: 1.35rem; }
  .reaches button .st-level small { display: inline; margin-left: 3px; }
  .reaches button svg { display: none; }
}
'''

# Plain: a printed almanac page. One serif face, no cards, no colour fills, ruled sections, light only.
PLAIN_CSS = r'''
html:root:root { --bg: #fbfaf7; --surface: #fbfaf7; --sunk: #f3f2ee; --ink: #1b2326; --muted: #55605f; --line: #d6d9d7; --line-strong: #8b9594;
  --water: #1b2326; --on-water: #fbfaf7; --water-soft: #f3f2ee; --ok: #2c5e3a; --warn: #7a4e10; --bad: #9e2c24;
  --ok-soft: transparent; --warn-soft: transparent; --bad-soft: transparent; --cheat: #1b2326; --on-cheat: #fbfaf7;
  --body: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; --mono: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  color-scheme: light; }
body { font-variant-numeric: tabular-nums; }
.wrap, .masthead, .testbar { max-width: 40rem; }
.masthead { border-bottom: 2px solid var(--ink); padding-bottom: 10px; }
.cards, .grid { grid-template-columns: 1fr !important; gap: 0; }
.panel, .fold { background: none; border: 0; border-radius: 0; border-top: 1px solid var(--line); padding: 16px 0; }
.wrap > .fold:first-of-type, .cards > .panel:first-child { border-top: 0; }
h2, .wx-head h2 { font-weight: 400; font-size: 0.82rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
.label, .wx dt, .ev-head, .sight-area h3, .rate-k { letter-spacing: 0.06em; }
.pill { padding: 0; background: none !important; font-weight: 400; font-style: italic; }
.pill::before { display: none; }
.chip { border: 0; background: none; padding: 0 6px 0 0; }
.chip.next { background: none; color: var(--ink); font-weight: 700; text-decoration: underline; }
.alert { background: none; border: 1px solid var(--bad); }
.notice-list li { padding-left: 0; }
.notice-list li::before { display: none; }
.notice-list li.urgent a { color: var(--bad); }
.reaches button, .venue, .sight, .check-list li, .food-menu { background: none; border-radius: 0; box-shadow: none; }
.reaches { gap: 0; border-top: 1px solid var(--line); }
.reaches button { border: 0; border-bottom: 1px solid var(--line); }
.reaches button[aria-pressed="true"] { box-shadow: none; border-bottom: 2px solid var(--ink); }
.big { color: var(--ink); }
button { border-radius: 0; }
input[type=number], input[type=time], input[type=text], input[type=datetime-local], select { border-radius: 0; background: #ffffff; }
'''

FOLD_JS = r'''<script>
// Test layouts: fold the extras into one-line rows, and keep one short footer.
document.addEventListener("DOMContentLoaded", function () {
  function fold(el, title, open) {
    if (!el) return;
    var d = document.createElement("details"); d.className = "fold"; if (open) d.open = true;
    var s = document.createElement("summary"); s.textContent = title; d.appendChild(s);
    el.parentNode.insertBefore(d, el); d.appendChild(el);
    return d;
  }
  var wrap = document.querySelector(".wrap");
  // Eating ashore, events and sights move out of the main flow into folded rows, then the depth tools, then sources.
  var tail = document.createElement("div"); tail.style.display = "grid"; tail.style.gap = "8px";
  var food = document.getElementById("food-panel"), ev = document.getElementById("events-box"),
      sights = document.getElementById("sights-section"), depth = document.getElementById("depth-correction"),
      credits = document.getElementById("credits");
  wrap.insertBefore(tail, depth);
  [food, ev, sights].forEach(function (el) { if (el) tail.appendChild(el); });
  fold(food, "Eat ashore"); fold(ev, "Events on the water"); fold(sights, "Sights");
  if (ev) ev.hidden = false;
  // Depth: keep the headline correction in view, fold the tools under it.
  var zone = depth && depth.querySelector(".depth-zone");
  if (zone) {
    var hero = zone.querySelector(".hero");
    if (hero) depth.insertBefore(hero, zone);
    fold(zone, "Depth at a spot, lead-line checks and the gauge");
  }
  fold(credits, "Sources and credits");
  var foot = document.createElement("p"); foot.className = "short-foot";
  foot.innerHTML = 'Data from the OPW, Met Éireann, Waterways Ireland and the ESB. No cookies, no tracking. <a href="mailto:info@leehughes.ie">Report a mistake</a>.';
  wrap.appendChild(foot);
  // Sections with nothing in them yet stay out of sight.
  setInterval(function () {
    var e = document.getElementById("events"); if (e && e.parentNode.closest(".fold")) e.closest(".fold").hidden = !e.children.length;
    var s = document.getElementById("sights"); if (s && s.closest(".fold")) s.closest(".fold").hidden = !s.children.length;
    var f = document.getElementById("food-box"); if (f && f.closest(".fold")) f.closest(".fold").hidden = f.hidden;
  }, 1000);
  // One short line under the notices.
  var nf = [].slice.call(document.querySelectorAll(".notices > .fine")).filter(function (p) { return /AI assistant/.test(p.textContent); })[0];
  if (nf) nf.innerHTML = 'Short AI summaries, not checked each time. <a href="https://www.waterwaysireland.org/news?tabId=tabbedsection&tabName=marinenotices" target="_blank" rel="noopener">Official notices on waterwaysireland.org</a>.';
});
</script>
'''

def build(name, label, css):
    p = h
    p = re.sub(r'<title>.*?</title>', '<title>Test: ' + label + ' · Shannon Almanac</title>', p, count=1, flags=re.S)
    p = p.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta name="robots" content="noindex">', 1)
    p = re.sub(r'<h1>.*?</h1>', '<h1>Shannon Almanac</h1>', p, count=1, flags=re.S)
    p = re.sub(r'<p class="sub">.*?</p>', '<p class="sub">Marine notices, forecasts, water levels and lock times, Killaloe to Lough Key.</p>', p, count=1, flags=re.S)
    p = re.sub(r'\s*<p class="sub">Trying a simpler layout:.*?</p>', '', p, count=1, flags=re.S)
    bar = ('<p class="testbar"><b>Test layout: ' + label + '.</b> Same live data as '
           '<a href="../../">the main page</a>. <a href="../' + ('plain' if name == 'trim' else 'trim') + '/">See the other test</a>.</p>\n')
    p = p.replace('<header class="masthead">', bar + '<header class="masthead">', 1)
    # The files live at the site root, two folders up.
    i = p.index('<script>')
    p = p[:i] + '<script>window.SHANNON_BASE = "../../";</script>\n' + p[i:]
    p = p.replace('</body>', '<style>' + css + '</style>\n' + FOLD_JS + '</body>', 1)
    os.makedirs(os.path.join(out, 'test', name), exist_ok=True)
    open(os.path.join(out, 'test', name, 'index.html'), 'w').write(p)
    print(name, len(p))

build('trim', 'Trim', TRIM_CSS)
build('plain', 'Plain', TRIM_CSS + PLAIN_CSS)
