# Fetch Met Éireann's inland lakes forecast from its open-data XML and update data.json.
# No AI in the loop: run by GitHub Actions alongside the gauges, and only written when a newer forecast is issued.
# It also keeps weather.status: what Met Éireann's file said at the last check, written only when that changes.
# Usage: update_weather.py <data.json>
import json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

FEED = "https://www.met.ie/Open_Data/xml/xInland_Lake_Forecast.xml"
LAKES = (("derg", "Derg"), ("ree", "Ree"), ("key", "Key"))   # page id, word in the lake's <area> text
FIELDS = (("wind", "wind"), ("weather", "weather"), ("visibility", "visibility"), ("overnight", "windsovernight"), ("outlook", "outlook"))

def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def clean(s): return re.sub(r"\s+", " ", s or "").strip()

def fetch():
    req = urllib.request.Request(FEED, headers={"User-Agent": "shannon-chart-depth (github.com/gettierswhole)", "Cache-Control": "no-cache"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=60).read())
    issued_el = root.find("issued")
    raw = None
    if issued_el is not None:
        raw = issued_el.get("issued-time") or issued_el.get("issued") or issued_el.text
    if not raw:
        raise ValueError("no issue time in the feed")
    issued = iso(datetime.fromisoformat(raw.strip()))
    lakes = {}
    for lake in root.iter("lake"):
        area = clean(lake.findtext("area"))
        for key, word in LAKES:
            if word in area and key not in lakes:
                entry = {}
                for name, tag in FIELDS:
                    text = clean(lake.findtext(tag))
                    if name == "outlook":
                        text = clean(re.sub(r"\b(Wind|Weather):\s*", "", text))
                    if text:
                        entry[name] = text
                if entry:
                    lakes[key] = entry
    return issued, lakes

# Met Éireann's automatic model (HARMONIE) point forecast: produced every hour with no forecaster involved,
# so it carries on when the written lakes forecast is late. Stored as compact hourly steps for the next 36 hours:
# [time, wind direction deg, wind speed m/s, gust m/s, rain mm in the hour to that time].
MODEL = "https://openaccess.pf.api.met.ie/metno-wdb2ts/locationforecast?lat={lat};long={lon}"
POINTS = {"derg": (52.95, -8.29), "ree": (53.55, -7.98), "key": (53.98, -8.24)}

def fetch_model(lat, lon, now):
    # The service's documented address is plain http; its https end often drops the connection. Try https first.
    body = None
    for url in (MODEL.format(lat=lat, lon=lon), MODEL.format(lat=lat, lon=lon).replace("https://", "http://", 1)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "shannon-chart-depth (github.com/gettierswhole)"})
            body = urllib.request.urlopen(req, timeout=60).read()
            break
        except Exception:
            if url.startswith("http://"):
                raise
    root = ET.fromstring(body)
    created = root.get("created")
    wind, rain = {}, {}
    for t in root.iter("time"):
        a, b = t.get("from"), t.get("to")
        if not a or not b:
            continue
        if a == b:
            dd, ff, fg = t.find(".//windDirection"), t.find(".//windSpeed"), t.find(".//windGust")
            if dd is not None and ff is not None:
                wind[a] = (round(float(dd.get("deg")), 0), round(float(ff.get("mps")), 1),
                           round(float(fg.get("mps")), 1) if fg is not None and fg.get("mps") else None)
        else:
            pr = t.find(".//precipitation")
            ta, tb = datetime.fromisoformat(a.replace("Z", "+00:00")), datetime.fromisoformat(b.replace("Z", "+00:00"))
            if pr is not None and (tb - ta).total_seconds() == 3600:
                rain[b] = round(float(pr.get("value") or 0), 1)
    steps = []
    for k in sorted(wind):
        tk = datetime.fromisoformat(k.replace("Z", "+00:00"))
        if now - timedelta(hours=1) <= tk <= now + timedelta(hours=36):
            d, s, g = wind[k]
            steps.append([iso(tk), d, s, g, rain.get(k)])
    if not created or len(steps) < 6:
        raise ValueError("model forecast had too few hourly steps")
    return iso(datetime.fromisoformat(created.replace("Z", "+00:00"))), steps

def update_model(w, now_dt):
    old = w.get("model") or {}
    lakes, created, errors = {}, None, []
    for key, (lat, lon) in POINTS.items():
        try:
            c, steps = fetch_model(lat, lon, now_dt)
            lakes[key] = {"steps": steps}
            created = max(created or c, c)
        except Exception as e:
            errors.append(key + ": " + type(e).__name__ + ": " + str(e)[:80])
    if not lakes:
        return {"modelCreated": None, "modelResult": "fetch failed: " + "; ".join(errors)}
    if str(old.get("created", "")) >= created:
        return {"modelCreated": created, "modelResult": "nothing newer"}
    w["model"] = {"created": created, "fetchedAt": iso(now_dt), "lakes": lakes, "source": "Met Éireann HARMONIE point forecast"}
    return {"modelCreated": created, "modelResult": "updated" + (" (missing " + "; ".join(errors) + ")" if errors else "")}

def main(path):
    data = json.load(open(path))
    now_dt = datetime.now(timezone.utc)
    now = iso(now_dt)
    w = data.setdefault("weather", {})
    old = w.get("lakes") or {}
    try:
        issued, lakes = fetch()
        if "derg" not in lakes or "ree" not in lakes:
            status = {"feedIssued": issued, "result": "Lough Derg or Lough Ree missing from the feed"}
        elif str(old.get("issued", "")) >= issued:
            status = {"feedIssued": issued, "result": "nothing newer"}
        else:
            w["lakes"] = {"issued": issued, "fetchedAt": now, "lakes": lakes, "source": "Met Éireann open data"}
            status = {"feedIssued": issued, "result": "updated"}
    except Exception as e:
        status = {"feedIssued": None, "result": "fetch failed: " + type(e).__name__ + ": " + str(e)[:160]}
    status.update(update_model(w, now_dt))
    prev = w.get("status") or {}
    changed = status["result"] == "updated" or status["modelResult"].startswith("updated") or {k: prev.get(k) for k in status} != status
    if changed:
        w["status"] = dict(status, checked=now)
        json.dump(data, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    print("weather: " + status["result"] + " (Met Éireann's file issued " + str(status["feedIssued"]) + ")")
    print("model: " + status["modelResult"] + " (run created " + str(status["modelCreated"]) + ")")

if __name__ == "__main__":
    main(sys.argv[1])
