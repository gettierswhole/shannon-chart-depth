# Build the Shannon Dashboard's data files from the public repository and the site's own database.
# Usage: python3 dash_export.py <repo dir> <db dir> <out dir>
#   <db dir> holds notices/live.json and events/live.json read from the Shannon Chart Depth page's database.
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

repo, dbdir, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
now = datetime.now(timezone.utc)
def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def db(path):
    try:
        d = json.load(open(os.path.join(dbdir, path)))
        return d.get("data", d) if isinstance(d, dict) and "data" in d and "version" in d else d
    except Exception:
        return None
def put(name, rows):
    json.dump(rows, open(os.path.join(out, name), "w"), ensure_ascii=False)

data = json.load(open(os.path.join(repo, "data.json")))

# Reference level each stretch is compared with (m OD Malin), as the site uses by default.
BANAGHER_OSL = 32.449
REACHES = [
    # 8 ft over the Killaloe upper (lake-side) cill, 30.52 m Poolbeg, as the CSIG's 2020 article says.
    ("derg", "Lough Derg", "portumna", "Portumna Bridge", 30.248, "Chart datum (8 ft over Killaloe upper cill)", 10),
    # Waterways Ireland's Banagher summer level (35.36) is on the OPW gauge but in their own figures, which run 2.911 m above OPW's Malin.
    ("mid", "Meelick – Athlone", "banagher", "Banagher", BANAGHER_OSL, "Ordinary summer level, Banagher", 15),
    # IWAI Athlone branch: 5 ft 6 in over the Athlone cill (32.609 m Malin, from their 2 Nov 2018 record low), read at Athlone Weir U/S.
    ("ree", "Lough Ree", "athloneus", "Athlone (above the weir)", 34.285, "Chart datum (5 ft 6 in over Athlone cill)", 10),
    ("key", "Upper Shannon", "carrick", "Carrick-on-Shannon", 40.270, "Ordinary summer level, Carrick pool", 15),
]
levels, history = [], []
cut = now - timedelta(days=7)
for i, (rid, name, doc, gname, ref, refname, band) in enumerate(REACHES):
    g = data["gauge"][doc]
    # Level 24 hours earlier: the history point nearest to then.
    hist = [h for h in g.get("history", []) if h.get("v") is not None]
    day_ago = None
    target = ts(g["time"]) - timedelta(hours=24)
    if hist:
        best = min(hist, key=lambda h: abs((ts(h["t"]) - target).total_seconds()))
        if abs((ts(best["t"]) - target).total_seconds()) <= 3 * 3600:
            day_ago = best["v"]
    levels.append({"order": i + 1, "reach": rid, "stretch": name, "gauge": gname, "level_m": g["level"],
                   "reading_at": g["time"], "reference_m": ref, "reference": refname, "band_cm": band,
                   "level_24h_ago_m": day_ago})
    for h in hist:
        if ts(h["t"]) >= cut:
            history.append({"reach": rid, "stretch": name, "t": h["t"], "level_m": h["v"]})
put("levels.json", levels)
# The Meelick-Athlone pool read at three points against its summer level (32.449 m Malin on OPW's scale), downstream last.
POOL = [("athlone", "Athlone, below the weir", 1), ("shannonbridge", "Shannonbridge", 2), ("banagher", "Banagher", 3)]
pool = []
for doc, place, order in POOL:
    g = data["gauge"].get(doc)
    if g and g.get("level") is not None:
        pool.append({"order": order, "gauge": doc, "place": place, "level_m": g["level"], "reading_at": g["time"],
                     "summer_level_m": BANAGHER_OSL, "vs_summer_cm": round((g["level"] - BANAGHER_OSL) * 100)})
put("pool.json", pool)
put("history.json", history)

w = data.get("weather", {})
LAKES = {"derg": "Lough Derg", "ree": "Lough Ree", "key": "Upper Shannon"}
wind = []
for k, v in (w.get("model", {}).get("lakes") or {}).items():
    for t, d, s, gst, rain in v.get("steps", []):
        wind.append({"lake": LAKES.get(k, k), "t": t, "direction_deg": d, "wind_ms": s, "gust_ms": gst, "rain_mm": rain})
put("wind.json", wind)
fc = []
lk = w.get("lakes") or {}
for k, v in (lk.get("lakes") or {}).items():
    fc.append({"lake": LAKES.get(k, k), "issued": lk.get("issued"), "wind": v.get("wind"), "weather": v.get("weather"),
               "visibility": v.get("visibility"), "overnight": v.get("overnight"), "outlook": v.get("outlook")})
put("forecast.json", fc)

notices_doc = db("notices/live.json") or data.get("notices", {}).get("live", {})
nrows = []
for c in notices_doc.get("closures", []):
    nrows.append({"key": "closure-" + c.get("date", ""), "kind": "Closure", "date": c.get("date"), "until": c.get("date"),
                  "title": "Locks and bridges closed: " + (c.get("why") or ""), "ref": c.get("notice"), "level": "urgent", "url": c.get("url")})
# A notice that has ended (lifted by an update, or past its last day) stays listed for 72 hours, marked as ended,
# the same as on the Chart Depth page.
from zoneinfo import ZoneInfo
def end_of_irish_day(d):
    nxt = datetime.fromisoformat(d) + timedelta(days=1)
    return nxt.replace(tzinfo=ZoneInfo("Europe/Dublin")).astimezone(timezone.utc)
for n in notices_doc.get("notices", []):
    end = None
    if n.get("ended"):
        end = ts(n["ended"])
    elif n.get("until"):
        try:
            e = end_of_irish_day(n["until"])
            end = e if e <= now else None
        except ValueError:
            end = None
    if end is not None and end > now:
        end = None
    if end is not None and now - end > timedelta(hours=72):
        continue
    if end is None:
        nrows.append({"key": "notice-" + str(n.get("no")), "kind": "Marine notice", "date": None, "until": n.get("until"),
                      "title": n.get("title"), "ref": "Marine Notice " + str(n.get("no")), "level": n.get("level") or "", "url": n.get("url")})
    else:
        how = (n.get("endedHow") or "ended").upper()
        when = end.astimezone(ZoneInfo("Europe/Dublin")).strftime("%a %-d %b, %H:%M")
        what = n.get("endedText") or ("Its last day has passed." if not n.get("ended") else "This notice has been lifted.")
        nrows.append({"key": "notice-" + str(n.get("no")), "kind": "Ended", "date": iso(end), "until": iso(end + timedelta(hours=72)),
                      "title": "%s %s: %s %s" % (how, when, n.get("title"), "(" + what + ")"),
                      "ref": "Marine Notice " + str(n.get("no")), "level": "ended", "url": n.get("url")})
put("notices.json", nrows)

events_doc = db("events/live.json") or data.get("events", {}).get("live", {})
erows = [{"key": e.get("date", "") + " " + e.get("title", ""), "date": e.get("date"), "end": e.get("end") or e.get("date"),
          "title": e.get("title"), "where": e.get("where"), "stretch": dict((r[0], r[1]) for r in REACHES).get(e.get("reach"), e.get("reach")),
          "source": e.get("source")} for e in events_doc.get("events", [])]
for n in events_doc.get("venueNews", []):
    erows.append({"key": "news " + n.get("venueId", "") + " " + n.get("received", ""), "date": n.get("received"), "end": n.get("until"),
                  "title": n.get("text"), "where": n.get("from"), "stretch": dict((r[0], r[1]) for r in REACHES).get(n.get("reach"), n.get("reach")),
                  "source": "Venue email"})
put("events.json", erows)

# Pipeline: when each moving part last did its job, and how old is too old (hours; null = only changes when there is news).
def git_last(author):
    try:
        return subprocess.check_output(["git", "-C", repo, "log", "-1", "--author=" + author, "--format=%cI"], text=True).strip() or None
    except Exception:
        return None
def norm(s):
    return iso(datetime.fromisoformat(s.replace("Z", "+00:00"))) if s else None
newest_reading = max(data["gauge"][r[2]]["time"] for r in REACHES)
food = data.get("food", {})
checked = [v.get("checked") for v in food.values() if v.get("checked")]
st = w.get("status", {})
pipeline = [
    {"part": "Gauge script (GitHub Action)", "what": "Copies OPW readings and Met Éireann forecasts into the public data every 30 minutes", "last_at": norm(git_last("gauge-bot")), "limit_h": 1.5},
    {"part": "OPW gauge readings", "what": "Newest reading time across the four gauges", "last_at": newest_reading, "limit_h": 2},
    {"part": "Model forecast", "what": "Met Éireann HARMONIE point forecast, made hourly", "last_at": (w.get("model") or {}).get("created"), "limit_h": 3},
    {"part": "Written lakes forecast", "what": "Met Éireann forecasters; the site switches to the model forecast past 18 hours", "last_at": lk.get("issued"), "limit_h": 18},
    {"part": "Forecast script last checked", "what": "Result: " + str(st.get("result")) + " (written), " + str(st.get("modelResult")) + " (model)", "last_at": st.get("checked"), "limit_h": 1.5},
    {"part": "Club calendars", "what": "Events list refreshed by the twice-monthly menus and hours task", "last_at": events_doc.get("updated"), "limit_h": 16 * 24},
    {"part": "Venue menus and hours", "what": "Oldest of the four stretches' venue checks", "last_at": min(checked) if checked else None, "limit_h": 16 * 24},
    {"part": "Marine notices", "what": "Last change to the notices list (changes only when Waterways Ireland issue one)", "last_at": notices_doc.get("updated"), "limit_h": None},
    {"part": "Public page", "what": "Last time the public copy of the page itself changed", "last_at": norm(git_last("Claude")), "limit_h": None},
    {"part": "Dashboard data", "what": "When this dashboard's saved data was last rebuilt", "last_at": iso(now), "limit_h": 4},
]
put("pipeline.json", pipeline)
print({f: len(json.load(open(os.path.join(out, f)))) for f in sorted(os.listdir(out))})
