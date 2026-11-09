// Keeps the public pages and their last data on the phone, so they open at once on a slow signal and with none.
// Pages: the saved copy is shown straight away and checked for a newer one in the background (used next time).
// Data files: the network first, the saved copy if the network fails. The page itself shows its last data
// straight away from the phone's own storage while the fresh files arrive.
var CACHE = "shannon-v2";
self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) {
    return Promise.all(["./", "live.json"].map(function (u) { return c.add(u).catch(function () {}); }));
  }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  var key = new Request(url.origin + url.pathname);
  var isPage = req.mode === "navigate" || /\/$|\.html$/.test(url.pathname);
  if (isPage) {
    e.respondWith(caches.open(CACHE).then(function (c) {
      return c.match(key).then(function (hit) {
        var net = fetch(req).then(function (res) {
          if (res && res.ok) c.put(key, res.clone());
          return res;
        });
        if (hit) { e.waitUntil(net.catch(function () {})); return hit; }
        return net;
      });
    }));
    return;
  }
  e.respondWith(
    fetch(req).then(function (res) {
      if (res && res.ok) { var copy = res.clone(); caches.open(CACHE).then(function (c) { c.put(key, copy); }); }
      return res;
    }).catch(function () {
      return caches.match(key).then(function (hit) { return hit || Response.error(); });
    })
  );
});
