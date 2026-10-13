# Assemble data.json for the public copy from database documents saved as JSON files.
# Usage: export_data.py <dir with collection/doc.json files> <out data.json>
import json, os, sys
root, out = sys.argv[1], sys.argv[2]
keep = {"gauge": ["portumna", "banagher", "hodsons", "carrick"], "food": ["derg", "mid", "ree", "key"], "notices": ["live"], "weather": ["lakes"], "events": ["live"]}
data = {}
for col, ids in keep.items():
    for d in ids:
        f = os.path.join(root, col, d + ".json")
        if os.path.exists(f):
            j = json.load(open(f))
            j = j.get("data", j) if isinstance(j, dict) and "data" in j and "version" in j else j
            data.setdefault(col, {})[d] = j
data["exported"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(data, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
print({k: list(v) for k, v in data.items() if isinstance(v, dict)})
