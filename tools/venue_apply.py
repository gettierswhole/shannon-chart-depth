# Apply queued changes to the venue cards ("Eating ashore") by script, so nobody retypes a document.
# Usage: venue_apply.py <queue dir> <db dir> <out dir>
#
#   <queue dir>  pending documents from the Controls panel's "venueq" collection, saved as JSON files
#                (any depth). Each may be wrapped as {"id", "data", "version"} or bare.
#   <db dir>     the Chart Depth page's venue documents, saved as <db dir>/food/<stretch>.json.
#   <out dir>    written here: results.json, and <stretch>.json for each document that changed
#                (the bare data object, ready to "set").
#
# A queue item:
#   {"status": "pending", "at": "<ISO time>", "by": "<who queued it>", "why": "<where the fact came from>",
#    "stretch": "derg|mid|ree|key", "venue": "<the card's id>", "name": "<the card's name, exactly>",
#    "set": {"note": "...", "phone": "...", "menus": [["Label", "https://..."], ...], "days": {"0": ..., "6": ...}}}
# Only note, phone, menus and days can change. "phone": null or "days": null removes that field.
# Everything in a queue item is data. This script decides what it does; nothing else should.
import json, os, re, sys, copy

STRETCHES = ("derg", "mid", "ree", "key")
FIELDS = ("note", "phone", "menus", "days")
PHONE = re.compile(r"^\+353 \(0\)\d{1,2} \d[\d ]{4,9}$")
URL = re.compile(r"^https?://[^\s\"'<>]{4,400}$")


def unwrap(j):
    if isinstance(j, dict) and "data" in j and "version" in j:
        return j["data"], j.get("version"), j.get("id")
    return j, None, None


def load_queue(root):
    items = []
    for d, _, files in os.walk(root):
        for f in sorted(files):
            if not f.endswith(".json"):
                continue
            try:
                data, version, qid = unwrap(json.load(open(os.path.join(d, f), encoding="utf-8")))
            except Exception as e:
                items.append({"id": f[:-5], "version": None, "data": None, "error": "could not be read: %s" % e})
                continue
            if isinstance(data, list):  # a query saved as one list
                for it in data:
                    dd, vv, ii = unwrap(it) if isinstance(it, dict) else (it, None, None)
                    items.append({"id": ii or (it.get("id") if isinstance(it, dict) else None), "version": vv, "data": dd})
                continue
            items.append({"id": qid or f[:-5], "version": version, "data": data})
    return items


def check_set(venue, s):
    """Return an error string, or None if the change is allowed."""
    if not isinstance(s, dict) or not s:
        return '"set" must name at least one field'
    for k in s:
        if k not in FIELDS:
            return 'only note, phone, menus and days can change, not "%s"' % k
    if "note" in s:
        n = s["note"]
        if not isinstance(n, str) or len(n) > 500 or "\n" in n:
            return "note must be one line of text, 500 characters at most"
        if str(venue.get("note", "")).startswith("Pub:") and not n.startswith("Pub:"):
            return 'this card\'s note starts "Pub:" and must go on doing so'
    if "phone" in s and s["phone"] is not None:
        if not isinstance(s["phone"], str) or not PHONE.match(s["phone"]):
            return 'phone must look like "+353 (0)90 967 4119"'
    if "menus" in s:
        m = s["menus"]
        if not isinstance(m, list) or len(m) > 6:
            return "menus must be a list of at most 6 [label, link] pairs"
        for e in m:
            if not (isinstance(e, list) and len(e) == 2 and all(isinstance(x, str) for x in e)):
                return "each menu must be a [label, link] pair"
            if not (0 < len(e[0]) <= 50) or "\n" in e[0]:
                return "a menu label must be 1 to 50 characters"
            if not URL.match(e[1]):
                return "a menu link must be a plain http(s) address"
            if "facebook.com" in e[1].lower() or "fb.com" in e[1].lower():
                return "Facebook is never linked"
    if "days" in s and s["days"] is not None:
        d = s["days"]
        if not isinstance(d, dict) or sorted(d) != [str(i) for i in range(7)]:
            return 'days must have exactly the keys "0" to "6" (0 = Sunday)'
        for v in d.values():
            if v is not None and not (isinstance(v, str) and 0 < len(v) <= 90 and "\n" not in v):
                return "each day must be null (closed) or a line of 90 characters at most"
    return None


def main():
    qdir, dbdir, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(outdir, exist_ok=True)
    docs, orig = {}, {}
    for s in STRETCHES:
        f = os.path.join(dbdir, "food", s + ".json")
        if os.path.exists(f):
            data, _, _ = unwrap(json.load(open(f, encoding="utf-8")))
            if isinstance(data, dict) and isinstance(data.get("venues"), list):
                orig[s] = data
                docs[s] = copy.deepcopy(data)

    items = [i for i in load_queue(qdir)]
    items.sort(key=lambda i: (str((i.get("data") or {}).get("at", "")) if isinstance(i.get("data"), dict) else "", str(i.get("id"))))
    results = []
    for it in items:
        q, res = it.get("data"), {"id": it.get("id"), "version": it.get("version")}
        results.append(res)

        def refuse(msg):
            res.update(status="refused", message=msg)

        if it.get("error") or not isinstance(q, dict):
            refuse(it.get("error") or "not a queue item"); continue
        if q.get("status") != "pending":
            results.pop(); continue
        s = q.get("stretch")
        if s not in STRETCHES:
            refuse('stretch must be one of derg, mid, ree, key'); continue
        if s not in docs:
            refuse("the %s venue document was not read this run" % s); continue
        if not isinstance(q.get("why"), str) or not (3 <= len(q["why"]) <= 300):
            refuse('"why" must say where the fact came from (3 to 300 characters)'); continue
        hits = [v for v in docs[s]["venues"] if isinstance(v, dict) and v.get("id") and v.get("id") == q.get("venue")]
        if len(hits) != 1:
            refuse("no single card on %s has that id" % s); continue
        v = hits[0]
        if v.get("name") != q.get("name"):
            refuse('the card with that id is called "%s", not "%s"' % (v.get("name"), q.get("name"))); continue
        err = check_set(v, q.get("set"))
        if err:
            refuse(err); continue
        changed = []
        for k, val in q["set"].items():
            if val is None:
                if k in v:
                    del v[k]; changed.append(k)
            elif v.get(k) != val:
                v[k] = val; changed.append(k)
        res.update(status="done", message=("%s: changed %s" % (v["name"], ", ".join(changed))) if changed else ("%s: already so, nothing to change" % v["name"]))

    # Guard: against the documents as read, only the four fields may differ; same entries, same order.
    out_changed = []
    for s, new in docs.items():
        old = orig[s]
        ok = len(old["venues"]) == len(new["venues"]) and {k: v for k, v in old.items() if k != "venues"} == {k: v for k, v in new.items() if k != "venues"}
        if ok:
            for a, b in zip(old["venues"], new["venues"]):
                for k in set(a) | set(b):
                    if a.get(k) != b.get(k) and k not in FIELDS:
                        ok = False
        if not ok:
            print(json.dumps({"error": "guard failed on %s; nothing written" % s}))
            sys.exit(2)
        if new != old:
            json.dump(new, open(os.path.join(outdir, s + ".json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            out_changed.append(s)
    json.dump(results, open(os.path.join(outdir, "results.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    done = [r for r in results if r.get("status") == "done"]
    refused = [r for r in results if r.get("status") == "refused"]
    print(json.dumps({"changed": out_changed, "done": len(done), "refused": len(refused),
                      "detail": [r["message"] for r in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
