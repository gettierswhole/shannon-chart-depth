// Keeps the public page and its last data on the phone, so it still opens with no signal.
// Network first for everything; the saved copy is used only when the network fails.
var CACHE = "shannon-v1";
self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(["./", "data.json"]); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  var key = url.origin === self.location.origin ? new Request(url.origin + url.pathname) : req;
  e.respondWith(
    fetch(req).then(function (res) {
      if (res && (res.ok || res.type === "opaque")) { var copy = res.clone(); caches.open(CACHE).then(function (c) { c.put(key, copy); }); }
      return res;
    }).catch(function () {
      return caches.match(key).then(function (hit) { return hit || caches.match(req, { ignoreSearch: true }); });
    })
  );
});
