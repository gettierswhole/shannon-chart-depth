# Fetch Met Éireann's inland lakes forecast from its open-data XML and update data.json.
# No AI in the loop: run by GitHub Actions alongside the gauges, and only written when a newer forecast is issued.
# It also keeps weather.status: what Met Éireann's file said at the last check, written only when that changes.
# Usage: update_weather.py <data.json>
import json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

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

def main(path):
    data = json.load(open(path))
    now = iso(datetime.now(timezone.utc))
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
    prev = w.get("status") or {}
    changed = status["result"] == "updated" or {k: prev.get(k) for k in status} != status
    if changed:
        w["status"] = dict(status, checked=now)
        json.dump(data, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    print("weather: " + status["result"] + " (Met Éireann's file issued " + str(status["feedIssued"]) + ")")

if __name__ == "__main__":
    main(sys.argv[1])
