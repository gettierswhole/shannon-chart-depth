# Builds the public, sign-in-free copy of the page from derg-depth.html.
# The copy reads its live data from small files beside it (made from data.json by tools/slim_data.py)
# instead of the artifact database.
# JS and CSS are minified (rjsmin + basic CSS strip) to reduce the gzipped page size.
import sys, re
try:
    import rjsmin
    _have_rjsmin = True
except ImportError:
    _have_rjsmin = False

src, out = sys.argv[1], sys.argv[2]
h = open(src).read()
# Accept either the page source or the published page as the artifact service returns it
# (wrapped in its own <html><head>...</head><body> skeleton): keep only the page itself.
if h.lstrip().lower().startswith('<!doctype') and '<body>' in h[:3000]:
    h = h[h.index('<body>') + len('<body>'):]
    if h.rstrip().endswith('</body></html>'):
        h = h.rstrip()[:-len('</body></html>')]
shim = r'''<script>
// Public copy: stand in for the artifact database with the small files beside the page, re-read every 10 minutes.
// Two-stage load for fast first paint on a slow connection:
//   1. slim.json (~3.5 kB gz): gauge levels only (no history). Delivers live readings immediately.
//   2. live.json (~9 kB gz): 7-day history for sparklines and trend. Loaded right after.
// Venues: food-<stretch>.json, loaded only for the reach on screen.
// Old lead-line check: history-<gauge>.json, loaded only when a check is entered over a week late.
// Fallback: if slim.json and live.json both fail, tries data.json.
(function () {
  var BASE = window.SHANNON_BASE || "";
  var subs = [], slim = null, cache = null, site, esb, food = {}, full = {}, foodWanted = {}, fullWanted = {};
  function get(name) {
    return fetch(BASE + name + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }
  function merged(key) {
    // Prefer live.json gauge (has history); fill from slim.json if live not yet arrived.
    var g = (cache && cache.gauge && cache.gauge[key]) || (slim && slim.gauge && slim.gauge[key]);
    if (!g || !full[key]) return g;
    var seen = {}, h = [];
    full[key].concat(g.history || []).forEach(function (p) { if (p && p.t && !seen[p.t]) { seen[p.t] = 1; h.push(p); } });
    h.sort(function (x, y) { return x.t < y.t ? -1 : 1; });
    var o = {}; for (var k in g) o[k] = g[k]; o.history = h; return o;
  }
  function pick(path) {
    if (path === "notices/site") return site;
    if (path === "esb/derg") return esb;
    var p = path.split("/");
    if (p[0] === "food") return food[p[1]] || (cache && cache.food ? cache.food[p[1]] : undefined);
    var src = cache || slim;
    if (!src) return undefined;
    if (p[0] === "gauge") return merged(p[1]);
    var col = src[p[0]];
    return col ? col[p[1]] : undefined;
  }
  function deliver(only) {
    subs.forEach(function (s) {
      if (only && s.path.indexOf(only) !== 0) return;
      var d = pick(s.path);
      if (d === undefined) return;
      try { s.cb({ exists: true, data: function () { return d; } }); } catch (e) {}
    });
  }
  function loadFood(rid) {
    if (!rid || foodWanted[rid]) return;
    foodWanted[rid] = 1;
    get("food-" + rid + ".json").then(function (j) { if (j) { food[rid] = j; deliver("food/" + rid); } else foodWanted[rid] = 0; });
  }
  function shownReach() { try { return localStorage.getItem("shannon.reach") || "derg"; } catch (e) { return "derg"; } }
  function load() {
    // Stage 1: slim.json — level + time only, ~3.5 kB gz. First paint with live readings.
    get("slim.json").then(function (j) {
      if (j && j.gauge) { slim = j; deliver(); }
      // Stage 2: live.json — 7-day history for sparklines/trend, ~9 kB gz.
      return get("live.json").then(function (k) {
        if (k && k.gauge) return k;
        // Last resort: full data.json (no-history split may not be deployed yet).
        return fetch(BASE + "data.json?t=" + Date.now(), { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
      });
    }).then(function (j) { if (j && j.gauge) { cache = j; deliver(); } });
    // Waterways Ireland's notices list, as the hourly check last found it (number, title and link only).
    get("notices_site.json").then(function (j) { if (j && Array.isArray(j.items)) { site = j; deliver("notices/site"); } });
    // The ESB's once-a-day Lough Derg levels (tools/update_esb.py), for the "Killaloe end" line.
    get("esb.json").then(function (j) { if (j && j.pierHead && typeof j.pierHead.level === "number") { esb = j; deliver("esb/derg"); } });
    foodWanted = {}; loadFood(shownReach());
  }
  // A lead-line check over a week old needs the gauge's month of readings: fetch it as the time is entered.
  function wantFull() {
    var el = document.getElementById("chk-when"), t = el && el.value ? new Date(el.value).getTime() : NaN;
    if (!isFinite(t) || Date.now() - t < 6.5 * 864e5) return;
    ["portumna", "athloneus"].forEach(function (key) {
      if (fullWanted[key]) return;
      fullWanted[key] = 1;
      get("history-" + key + ".json").then(function (j) {
        if (j && Array.isArray(j.history)) { full[key] = j.history; deliver("gauge/" + key); } else fullWanted[key] = 0;
      });
    });
  }
  document.addEventListener("change", function (e) { if (e.target && e.target.id === "chk-when") wantFull(); }, true);
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t && t.closest && t.closest("#chk-save")) wantFull();
    if (t && t.closest && t.closest("#reaches")) setTimeout(function () { loadFood(shownReach()); }, 0);
  }, true);
  var db = {
    doc: function (path) {
      return {
        onSnapshot: function (cb) {
          subs.push({ path: path, cb: cb });
          var d = pick(path);
          if (d !== undefined) { try { cb({ exists: true, data: function () { return d; } }); } catch (e) {} }
          return function () {};
        },
        set: function () { return Promise.reject(new Error("read-only")); }
      };
    }
  };
  window.claude = { use: function (name) { return name === "db" ? Promise.resolve(db) : Promise.reject(new Error("unavailable")); } };
  load(); setInterval(load, 10 * 60 * 1000);
  if ("serviceWorker" in navigator) { try { navigator.serviceWorker.register(BASE + "sw.js"); } catch (e) {} }
})();
</script>
<style>.rate-you, .rate-gap, .scorecard { display: none !important; }</style>
'''
# The public copy goes by its own name. The source page's name stays in a comment, which the sync task checks for.
import re
h = h.replace('<title>Shannon Chart Depth</title>', '<title>de Selby&#8217;s All Knowing Shannon Almanac</title>\n<!-- Public copy of the Shannon Chart Depth page -->', 1)
h = h.replace('<h1>Shannon Chart Depth</h1>', '<h1>de Selby&#8217;s All Knowing Shannon Almanac</h1>', 1)
h = re.sub(r'<p class="sub">.*?</p>', '<p class="sub">Marine notices, forecasting, water levels and lock times for the Shannon, Killaloe to Lough Key. Depth correction at the foot of the page.</p>\n  <p class="sub">Trying a simpler layout: <a href="test/trim/">Trim</a> · <a href="test/plain/">Plain</a></p>', h, count=1, flags=re.S)
i = h.index('<script>')
h = h[:i] + shim + h[i:]
h = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
     '<meta name="description" content="Live Shannon water levels against CSIG chart datum, with lake forecasts, lock times, marine notices and places to eat ashore.">\n'
     '</head>\n<body>\n' + h + '\n</body>\n</html>\n')
# Minify inline JS and CSS to reduce gzipped page size (~8-9 kB gz saving).
if _have_rjsmin:
    def _min_script(m):
        return '<script>' + rjsmin.jsmin(m.group(1)) + '</script>'
    h = re.sub(r'<script>(.*?)</script>', _min_script, h, flags=re.S)
# Basic CSS: strip comments and collapse whitespace (saves ~1 kB gz).
def _min_style(m):
    css = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S)
    css = re.sub(r'\s+', ' ', css)
    css = re.sub(r' ?([{};:,>+~]) ?', r'\1', css)
    return '<style>' + css.strip() + '</style>'
h = re.sub(r'<style>(.*?)</style>', _min_style, h, flags=re.S)
open(out, 'w').write(h)
