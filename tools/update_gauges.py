# Fetch the Shannon gauges straight from the OPW and update data.json.
# No AI in the loop: same sanity checks as before, run by GitHub Actions every 30 minutes.
# Usage: update_gauges.py <data.json>
#
# Sources, both OPW, both in m OD Malin:
# - Hydro-Data (waterlevel.ie/hydro-data): each station's last 7 days of 15-minute readings. Main source;
#   it also fills any hours missed while a source was down.
# - The older live feed (waterlevel.ie/geojson/latest/): latest reading only. Used if it is newer.
# A source that fails is skipped; the script only fails if neither gives anything at all.
import json, sys, urllib.request
from datetime import datetime, timezone, timedelta

FEED = "https://waterlevel.ie/geojson/latest/"
HYDRO = "https://waterlevel.ie/hydro-data/data/internet/stations/0/{no}/S/week.json"
UA = {"User-Agent": "shannon-chart-depth (github.com/gettierswhole)"}
GAUGES = {  # doc id: (station_ref, gauge zero m OD Malin)
    "portumna": ("0000025341", 29.169),
    "banagher": ("0000025017", 30.330),
    "hodsons": ("0000026088", 32.549),
    # Lough Ree is read at Athlone, above the weir (the quay by Athlone Castle): the CSIG datum is 5.5 ft over the Athlone lock cill.
    "athloneus": ("0000026333", 32.137),
    "carrick": ("0000026324", 38.888),
    # Extra gauges on the Meelick-Athlone pool, so it can be read at both ends, not just at Banagher.
    "athlone": ("0000026027", 30.471),        # Athlone, below the weir
    "shannonbridge": ("0000026028", 30.406),
}
HISTORY_KEEP = 168          # one point an hour at most: a week
HISTORY_STEP = timedelta(minutes=55)

def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def get_json(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))

def live_feed(log):
    """Latest reading per gauge from the older feed: {doc: (time, level)}."""
    try:
        feed = get_json(FEED)
    except Exception as e:
        log.append(f"live feed unavailable: {e}")
        return {}
    by = {}
    for f in feed.get("features", []):
        p = f.get("properties", {})
        by[(p.get("station_ref"), p.get("sensor_ref"))] = p
    out = {}
    for doc, (ref, zero) in GAUGES.items():
        p, level = by.get((ref, "OD")), None
        if p and p.get("value") not in (None, ""):
            level = float(p["value"])
        else:
            p = by.get((ref, "0001"))
            if p and p.get("value") not in (None, ""):
                level = float(p["value"]) + zero
        if level is not None:
            out[doc] = [(ts(p["datetime"]), level)]
    return out

def hydro(doc, ref, log):
    """The last week of readings from Hydro-Data, oldest first: [(time, level)]."""
    try:
        j = get_json(HYDRO.format(no=int(ref)))
        rows = j[0]["data"]
    except Exception as e:
        log.append(f"{doc}: Hydro-Data unavailable: {e}")
        return []
    pts = []
    for r in rows:
        try:
            if r[1] is None or (len(r) > 2 and r[2] is not None and int(r[2]) < 0):
                continue
            pts.append((ts(r[0]), float(r[1])))
        except Exception:
            continue
    return sorted(pts)

def main(path):
    data = json.load(open(path))
    now = datetime.now(timezone.utc)
    log = []
    live = live_feed(log)
    changed, any_source = False, bool(live)
    for doc, (ref, zero) in GAUGES.items():
        pts = hydro(doc, ref, log)
        any_source = any_source or bool(pts)
        if doc in live and (not pts or live[doc][0][0] > pts[-1][0]):
            pts = pts + live[doc]
        old = data.setdefault("gauge", {}).get(doc) or {}
        ot = ts(old["time"]) if old.get("time") else None
        ol = old.get("level")
        new = [p for p in pts if p[1] > 20 and (ot is None or p[0] > ot)]
        if not new:
            log.append(f"{doc}: nothing newer than {old.get('time')}"); continue
        # Sanity checks, step by step from the stored reading: no jump over 1.5 m, nor over 0.30 m within 6 hours.
        hist = [h for h in old.get("history", []) if isinstance(h, dict) and "t" in h and "v" in h]
        last_t, last_v, kept, rejected = ot, ol, None, 0
        for t, v in new:
            if last_v is not None:
                d = abs(v - last_v)
                if d > 1.5 or (d > 0.30 and last_t is not None and t - last_t < timedelta(hours=6)):
                    rejected += 1; continue
            if not hist or t - ts(hist[-1]["t"]) >= HISTORY_STEP:
                hist.append({"t": iso(t), "v": round(v, 3)})
            last_t, last_v, kept = t, v, (t, v)
        if kept is None:
            log.append(f"{doc}: rejected {rejected} reading(s) jumping from {ol}"); continue
        hist = hist[-HISTORY_KEEP:]
        data["gauge"][doc] = {**old, "level": round(kept[1], 3), "time": iso(kept[0]), "fetchedAt": iso(now), "history": hist, "source": "OPW"}
        changed = True
        log.append(f"{doc}: {kept[1]:.3f} at {iso(kept[0])}" + (f" ({rejected} rejected)" if rejected else ""))
    if changed:
        json.dump(data, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    print("\n".join(log))
    if not any_source:
        sys.exit("No OPW source answered")

if __name__ == "__main__":
    main(sys.argv[1])
