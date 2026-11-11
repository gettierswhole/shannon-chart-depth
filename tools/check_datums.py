# Check datums.json before it is published for the OpenCPN plugin.
# The plugin refuses a file it cannot read, but a wrong number in a valid
# file would reach every boat, so the figures are range-checked here too.
# Usage: python3 tools/check_datums.py datums.json
import json, sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
errors = []
def need(cond, msg):
    if not cond:
        errors.append(msg)

need(d.get("schema") == 1, "schema must be 1")
ids = [s.get("id") for s in d.get("stretches", [])]
need(sorted(ids) == ["derg", "key", "mid", "ree"], "expected the four stretches, got %s" % ids)
for s in d.get("stretches", []):
    sid = s.get("id")
    dt = s.get("datum")
    need(dt is not None and 25 < dt.get("level", 0) < 45, "%s: datum level out of range" % sid)
    need(0.02 <= s.get("band", 0) <= 0.5, "%s: band out of range" % sid)
    need(s.get("gauge", {}).get("station", "").isdigit(), "%s: no OPW station" % sid)
    b = s.get("boundary") or []
    need(len(b) >= 4 and all(51 < p[0] < 56 and -11 < p[1] < -5 for p in b), "%s: bad boundary" % sid)
for z in d.get("lockZones", []):
    need(50 <= z.get("r", 0) <= 1000 and 51 < z.get("lat", 0) < 56, "lock zone %s out of range" % z.get("name"))
need(len(d.get("lockZones", [])) >= 10, "lock zones missing")
if errors:
    print("datums.json failed its checks:\n  " + "\n  ".join(errors))
    sys.exit(1)
print("datums.json OK: " + ", ".join("%s %.3f m ±%.2f" % (s["id"], s["datum"]["level"], s["band"]) for s in d["stretches"]))
