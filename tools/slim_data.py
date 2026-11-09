# Makes the small files the public page loads, from data.json (which stays the full record other tools read).
#   live.json            everything the page needs straight away: gauges with a week of hourly history,
#                        notices, forecasts and events. No venues.
#   food-<stretch>.json  the venues for one stretch, loaded only for the stretch on screen.
#   history-<gauge>.json a gauge's full month of history, loaded only for a lead-line check entered over a week late.
# Writes a file only when its content changes, so an unchanged run leaves nothing to commit.
# Usage: python3 tools/slim_data.py data.json <out dir>
import json, os, sys
from datetime import datetime, timedelta, timezone

WEEK = timedelta(days=7, hours=6)  # a little over a week, so the 7-day trend always has its start point


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write(path, text):
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except FileNotFoundError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def parse(t):
    return datetime.fromisoformat(str(t).replace("Z", "+00:00"))


def main(src, out):
    data = json.load(open(src, encoding="utf-8"))
    changed = []
    live = {k: v for k, v in data.items() if k != "food"}
    gauges = {}
    for key, g in (data.get("gauge") or {}).items():
        g = dict(g)
        hist = g.get("history") if isinstance(g.get("history"), list) else []
        if hist:
            if write(os.path.join(out, "history-%s.json" % key), dump({"history": hist})):
                changed.append("history-%s.json" % key)
            try:
                cut = parse(g.get("time") or hist[-1]["t"]) - WEEK
                g["history"] = [p for p in hist if p and p.get("t") and parse(p["t"]) >= cut]
            except (ValueError, KeyError, TypeError):
                g["history"] = hist[-180:]
        gauges[key] = g
    live["gauge"] = gauges
    if write(os.path.join(out, "live.json"), dump(live)):
        changed.append("live.json")
    for rid, doc in (data.get("food") or {}).items():
        if write(os.path.join(out, "food-%s.json" % rid), dump(doc)):
            changed.append("food-%s.json" % rid)
    print("changed: " + (", ".join(changed) if changed else "nothing"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ".")
