# Assemble data.json for the public copy from database documents saved as JSON files.
# Usage: export_data.py <dir with collection/doc.json files> <data.json to update>
#
# - Gauges: the GitHub Action (tools/update_gauges.py) owns them. A gauge from the artifact
#   is used only if it is newer than the one already in data.json, so either feed can keep it going.
# - Lake forecast and model forecast: the same Action fetches both from Met Éireann's open data; the newer one wins.
# - Anything that came from email (venue news, events from club emails) stays on the private page:
#   a sender address can be forged, so it is never published here.
# - Marine notices are kept only when they link to waterwaysireland.org.
import json, os, sys, datetime
root, out = sys.argv[1], sys.argv[2]
keep = {"gauge": ["portumna", "banagher", "hodsons", "carrick"], "food": ["derg", "mid", "ree", "key"],
        "notices": ["live"], "weather": ["lakes", "model"], "events": ["live"]}
try:
    old = json.load(open(out))
except Exception:
    old = {}
data = {}
for col, ids in keep.items():
    for d in ids:
        f = os.path.join(root, col, d + ".json")
        v = None
        if os.path.exists(f):
            j = json.load(open(f))
            v = j.get("data", j) if isinstance(j, dict) and "data" in j and "version" in j else j
        prev = (old.get(col) or {}).get(d)
        if col == "gauge" and prev and v and str(prev.get("time", "")) >= str(v.get("time", "")):
            v = prev
        if col == "weather" and d == "lakes" and prev and v and str(prev.get("issued", "")) >= str(v.get("issued", "")):
            v = prev
        if col == "weather" and d == "model" and prev and v and str(prev.get("created", "")) >= str(v.get("created", "")):
            v = prev
        if v is None:
            v = prev
        if v is not None:
            data.setdefault(col, {})[d] = v

# The Action's record of what Met Éireann's files said at its last check.
if (old.get("weather") or {}).get("status"):
    data.setdefault("weather", {})["status"] = old["weather"]["status"]

ev = (data.get("events") or {}).get("live")
if isinstance(ev, dict):
    ev = dict(ev)
    ev["events"] = [e for e in ev.get("events", []) if "email" not in str(e.get("source", "")).lower()]
    ev["venueNews"] = []
    data["events"]["live"] = ev
no = (data.get("notices") or {}).get("live")
if isinstance(no, dict):
    no = dict(no)
    ok = lambda u: str(u).startswith("https://www.waterwaysireland.org/")
    no["notices"] = [n for n in no.get("notices", []) if ok(n.get("url"))]
    no["closures"] = [c for c in no.get("closures", []) if ok(c.get("url"))]
    data["notices"]["live"] = no

data["exported"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(data, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
print({k: list(v) for k, v in data.items() if isinstance(v, dict)})
