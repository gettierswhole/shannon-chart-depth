# Fetch Met Éireann's inland lakes forecast from its open-data XML and update data.json.
# No AI in the loop: run by GitHub Actions alongside the gauges, and only written when a newer forecast is issued.
# Usage: update_weather.py <data.json>
import json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

FEED = "https://www.met.ie/Open_Data/xml/xInland_Lake_Forecast.xml"
LAKES = (("derg", "Derg"), ("ree", "Ree"), ("key", "Key"))   # page id, word in the lake's <area> text
FIELDS = (("wind", "wind"), ("weather", "weather"), ("visibility", "visibility"), ("overnight", "windsovernight"), ("outlook", "outlook"))

def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def clean(s): return re.sub(r"\s+", " ", s or "").strip()

def main(path):
    data = json.load(open(path))
    req = urllib.request.Request(FEED, headers={"User-Agent": "shannon-chart-depth (github.com/gettierswhole)", "Cache-Control": "no-cache"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=60).read())
    issued_el = root.find("issued")
    raw = None
    if issued_el is not None:
        raw = issued_el.get("issued-time") or issued_el.get("issued") or issued_el.text
    if not raw:
        print("weather: no issue time in the feed"); return
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
    if "derg" not in lakes or "ree" not in lakes:
        print("weather: Lough Derg or Lough Ree missing from the feed; nothing written"); return
    old = (data.get("weather") or {}).get("lakes") or {}
    if str(old.get("issued", "")) >= issued:
        print("weather: nothing newer than " + str(old.get("issued"))); return
    data.setdefault("weather", {})["lakes"] = {"issued": issued, "fetchedAt": iso(datetime.now(timezone.utc)),
                                              "lakes": lakes, "source": "Met Éireann open data"}
    json.dump(data, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
    print("weather: forecast issued " + issued + " for " + ", ".join(sorted(lakes)))

if __name__ == "__main__":
    main(sys.argv[1])
