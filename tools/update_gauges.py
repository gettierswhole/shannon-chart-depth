# Fetch the four Shannon gauges straight from the OPW's public feed and update data.json.
# No AI in the loop: same sanity checks as before, run by GitHub Actions every 30 minutes.
# Usage: update_gauges.py <data.json>
import json, sys, urllib.request
from datetime import datetime, timezone, timedelta

FEED = "https://waterlevel.ie/geojson/latest/"
GAUGES = {  # doc id: (station_ref, gauge zero m OD Malin)
    "portumna": ("0000025341", 29.169),
    "banagher": ("0000025017", 30.330),
    "hodsons": ("0000026088", 32.549),
    "carrick": ("0000026324", 38.888),
}
HISTORY_KEEP = 168          # one point an hour at most: a week
HISTORY_STEP = timedelta(minutes=55)

def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def main(path):
    data = json.load(open(path))
    req = urllib.request.Request(FEED, headers={"User-Agent": "shannon-chart-depth (github.com/gettierswhole)"})
    feed = json.load(urllib.request.urlopen(req, timeout=60))
    by = {}
    for f in feed.get("features", []):
        p = f.get("properties", {})
        by[(p.get("station_ref"), p.get("sensor_ref"))] = p
    now = datetime.now(timezone.utc)
    changed, log = False, []
    for doc, (ref, zero) in GAUGES.items():
        p = by.get((ref, "OD"))
        level = None
        if p and p.get("value") not in (None, ""):
            level = float(p["value"])
        else:
            p = by.get((ref, "0001"))
            if p and p.get("value") not in (None, ""):
                level = float(p["value"]) + zero
        if level is None:
            log.append(f"{doc}: not in feed"); continue
        t = ts(p["datetime"])
        old = data.setdefault("gauge", {}).get(doc) or {}
        if old.get("time"):
            ot, ol = ts(old["time"]), old.get("level")
            if t <= ot: log.append(f"{doc}: nothing newer than {old['time']}"); continue
            if ol is not None:
                d = abs(level - ol)
                if d > 1.5 or (d > 0.30 and t - ot < timedelta(hours=6)):
                    log.append(f"{doc}: rejected jump {ol:.3f} -> {level:.3f}"); continue
        hist = [h for h in old.get("history", []) if isinstance(h, dict) and "t" in h and "v" in h]
        point = {"t": iso(t), "v": round(level, 3)}
        if not hist or t - ts(hist[-1]["t"]) >= HISTORY_STEP:
            hist.append(point)
        hist = hist[-HISTORY_KEEP:]
        data["gauge"][doc] = {**old, "level": round(level, 3), "time": iso(t), "fetchedAt": iso(now), "history": hist, "source": "OPW feed"}
        changed = True
        log.append(f"{doc}: {level:.3f} at {iso(t)}")
    if changed:
        json.dump(data, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    print("\n".join(log))

if __name__ == "__main__":
    main(sys.argv[1])
