# Builds the public, sign-in-free copy of the page from derg-depth.html.
# The copy reads its live data from data.json beside it instead of the artifact database.
import sys
src, out = sys.argv[1], sys.argv[2]
h = open(src).read()
shim = r'''<script>
// Public copy: stand in for the artifact database with data.json, re-read every 10 minutes.
(function () {
  var subs = [], cache = null;
  function pick(path) {
    if (!cache) return undefined;
    var p = path.split("/");
    var col = cache[p[0]];
    return col ? col[p[1]] : undefined;
  }
  function deliver() {
    subs.forEach(function (s) {
      var d = pick(s.path);
      try { s.cb({ exists: d !== undefined, data: function () { return d; } }); } catch (e) {}
    });
  }
  function load() {
    fetch("data.json?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) { cache = j; deliver(); } })
      .catch(function () {});
  }
  var db = {
    doc: function (path) {
      return {
        onSnapshot: function (cb) { subs.push({ path: path, cb: cb }); if (cache) deliver(); return function () {}; },
        set: function () { return Promise.reject(new Error("read-only")); }
      };
    }
  };
  window.claude = { use: function (name) { return name === "db" ? Promise.resolve(db) : Promise.reject(new Error("unavailable")); } };
  load(); setInterval(load, 10 * 60 * 1000);
  if ("serviceWorker" in navigator) { try { navigator.serviceWorker.register("sw.js"); } catch (e) {} }
})();
</script>
<style>.rate-you, .rate-gap, .scorecard { display: none !important; }</style>
'''
i = h.index('<script>')
h = h[:i] + shim + h[i:]
h = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
     '<meta name="description" content="Live Shannon water levels against CSIG chart datum, with lake forecasts, lock times, marine notices and places to eat ashore.">\n'
     '</head>\n<body>\n' + h + '\n</body>\n</html>\n')
open(out, 'w').write(h)
