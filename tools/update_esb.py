# Reads the ESB's daily 09:00 levels for Lough Derg (Pier Head, Killaloe and Portumna Bridge) and the daily
# flows out of the lake (Ardnacrusha, and the Parteen Weir total) from the chart PDFs the ESB publish, and
# writes them to esb.json.
#
# Why: the Lough Derg chart datum is set at Killaloe, but the page's live gauge is at Portumna, at the other
# end of the lake. Pier Head shows the Killaloe end. See claude/esb-pier-head.md in the project notes.
#
# The ESB give one reading a day, levels in metres over Poolbeg datum and flows in cubic metres per second,
# and each file holds about 30 days. The flows are kept to see how the lake's slope from Portumna to
# Killaloe goes with the flow leaving it; the page does not use them.
# esb.json keeps every day seen, so the record grows past 30 days.
#
# Cross-check (added 24 Nov 2026). The lake falls from Portumna to Killaloe, so Pier Head should read below
# Portumna. Any morning where it reads above is listed in esb.json under "reversed" and the run prints a
# warning. Such a pair is kept as the ESB gave it: whether a real reversal can happen is not known.
# One day is put right, under "corrections": see CORRECTIONS below.
#
# Nothing is guessed. If a file cannot be fetched or does not read as expected, that gauge is left as it
# was and the script exits with an error, so the run shows as failed.
#
# Usage: python3 tools/update_esb.py esb.json            (fetch and update)
#        python3 tools/update_esb.py --parse pierHead file.pdf    (print what a saved PDF holds, read as that gauge)
#        python3 tools/update_esb.py --recheck esb.json    (no fetch: apply the corrections and the cross-check)
import datetime, json, re, sys, urllib.request, zlib
from zoneinfo import ZoneInfo

BASE = "http://www.esbhydro.ie/Shannon/"
# Lough Derg has stood between 32.0 (statutory minimum) and 34.76 (Portumna, Nov 2009) m Poolbeg.
# Ardnacrusha takes up to about 400 m3/s; the Parteen total has passed 650 in floods.
GAUGES = {
    "pierHead": {"file": "06-Pier-Head-Killaloe.pdf", "name": "Pier Head, Killaloe", "field": "level",
                 "value": r"^\d\d\.\d\d$", "low": 31.5, "high": 35.5, "jump": 0.6},
    "portumna": {"file": "05-Portumna-Bridge.pdf", "name": "Portumna Bridge", "field": "level",
                 "value": r"^\d\d\.\d\d$", "low": 31.5, "high": 35.5, "jump": 0.6},
    "ardnacrusha": {"file": "07-Total-Ardnacrusha-Flow.pdf", "name": "Ardnacrusha, total average daily flow", "field": "flow",
                    "value": r"^\d{1,4}(\.\d+)?$", "low": -0.001, "high": 700, "jump": None},
    "parteen": {"file": "08-Total-Parteen-Weir-Flow.pdf", "name": "Parteen Weir, total flow (Ardnacrusha plus the old river)", "field": "flow",
                "value": r"^\d{1,4}(\.\d+)?$", "low": -0.001, "high": 1500, "jump": None},
}
# Days where the ESB's files hold the two Lough Derg levels the wrong way round. "published" is what the
# ESB's files say; the two values are exchanged when, and only when, a file still says exactly that.
# 5 Nov 2026: the ESB's "Portumna" 33.30 less OPW Portumna 25341 at 09:00 (30.673 m Malin) is 2.627, against
# 2.69 to 2.74 on the other 29 days; the ESB's "Pier Head" 33.40 less the same is 2.727, which fits. OPW's
# Portumna trace rose smoothly through that day. Worked 24 Nov 2026; see claude/esb-pier-head.md.
CORRECTIONS = {
    "2026-11-05T09:00:00Z": {"published": {"pierHead": 33.40, "portumna": 33.30},
                             "why": "The ESB's files have the Pier Head and Portumna levels exchanged for this day, "
                                    "judged against OPW's Portumna gauge 25341 at the same hour. Held here the right way round."},
}
PAIR = {"pierHead": "portumna", "portumna": "pierHead"}
AGENT = "shannon-chart-depth (github.com/gettierswhole/shannon-chart-depth)"
DUBLIN = ZoneInfo("Europe/Dublin")
MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
STAMP = re.compile(r"^(\d\d)-([A-Z][a-z]{2})-(\d\d) (\d\d):(\d\d):(\d\d)$")


def streams(pdf):
    """Every flate-compressed stream in the file, inflated."""
    for m in re.finditer(rb"stream\r?\n", pdf):
        end = pdf.find(b"endstream", m.end())
        if end < 0:
            continue
        try:
            yield zlib.decompress(pdf[m.end():end])
        except zlib.error:
            try:
                yield zlib.decompressobj().decompress(pdf[m.end():end])
            except zlib.error:
                continue


def pdf_string(s):
    """The text of one PDF literal string body, with its backslash escapes undone."""
    return re.sub(r"\\([()\\])", r"\1", s)


def chunks(content):
    """(x, y, text) for each piece of text in a page's content stream."""
    out = []
    for block in re.findall(r"BT(.*?)ET", content, re.S):
        x = y = None
        for m in re.finditer(r"1 0 0 1 (-?[\d.]+) (-?[\d.]+) Tm|\[(.*?)\]\s*TJ|\(((?:[^()\\]|\\.)*)\)\s*Tj", block, re.S):
            if m.group(1) is not None:
                x, y = float(m.group(1)), float(m.group(2))
            elif x is not None:
                if m.group(3) is not None:
                    text = "".join(pdf_string(p) for p in re.findall(r"\(((?:[^()\\]|\\.)*)\)", m.group(3)))
                else:
                    text = pdf_string(m.group(4))
                out.append((x, y, text.strip()))
    return out


def readings(pdf, value):
    """{UTC time: value} from the table of daily readings: a timestamp and a value on the same line."""
    VALUE = re.compile(value)
    found = {}
    for raw in streams(pdf):
        content = raw.decode("latin-1")
        if "TJ" not in content and "Tj" not in content:
            continue
        cs = chunks(content)
        stamps = [(x, y, STAMP.match(t)) for x, y, t in cs if STAMP.match(t)]
        values = [(x, y, float(t)) for x, y, t in cs if VALUE.match(t)]
        for sx, sy, m in stamps:
            same = [v for vx, vy, v in values if abs(vy - sy) < 0.6 and vx > sx]
            if len(same) != 1:
                continue
            d, mon, yy, hh, mm, ss = m.groups()
            if mon not in MONTHS:
                continue
            local = datetime.datetime(2000 + int(yy), MONTHS[mon], int(d), int(hh), int(mm), int(ss), tzinfo=DUBLIN)
            t = local.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if t in found and found[t] != same[0]:
                raise ValueError("two different values for " + t)
            found[t] = same[0]
    return found


def check(found, now, g):
    """Refuse anything that does not look like a month of daily readings for this gauge."""
    if len(found) < 20:
        raise ValueError("only %d readings found; expected about 30" % len(found))
    if not all(g["low"] < v < g["high"] for v in found.values()):
        raise ValueError("a value outside %.1f to %.1f" % (g["low"], g["high"]))
    ts = sorted(found)
    newest = datetime.datetime.strptime(ts[-1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    if newest > now + datetime.timedelta(hours=1):
        raise ValueError("newest reading is in the future: " + ts[-1])
    steps = [abs(found[b] - found[a]) for a, b in zip(ts, ts[1:])]
    if g["jump"] is not None and max(steps) > g["jump"]:
        raise ValueError("a jump of %.2f between days" % max(steps))


def correct(key, days):
    """Exchange a known wrong-way-round level, if the day still holds the figure the ESB published."""
    if key not in PAIR:
        return
    for t, c in CORRECTIONS.items():
        if t in days and abs(days[t] - c["published"][key]) < 0.005:
            days[t] = c["published"][PAIR[key]]


def history(doc, key):
    return {p["t"]: p["v"] for p in (doc.get(key) or {}).get("history", []) if isinstance(p, dict) and "t" in p and "v" in p}


def crosscheck(doc):
    """Set doc["corrections"] and doc["reversed"] from the two level histories. True if either changed."""
    pier, port = history(doc, "pierHead"), history(doc, "portumna")
    corrections = []
    for t in sorted(CORRECTIONS):
        c = CORRECTIONS[t]["published"]
        if t in pier and t in port and abs(pier[t] - c["portumna"]) < 0.005 and abs(port[t] - c["pierHead"]) < 0.005:
            corrections.append({"t": t, "published": c, "held": {"pierHead": pier[t], "portumna": port[t]},
                                "why": CORRECTIONS[t]["why"]})
    reversed_days = [t for t in sorted(pier) if t in port and pier[t] > port[t] + 0.005]
    for t in reversed_days:
        print("::warning::Pier Head reads above Portumna on %s (%.2f against %.2f). Kept as the ESB gave it; check it."
              % (t, pier[t], port[t]))
    changed = doc.get("corrections", []) != corrections or doc.get("reversed", []) != reversed_days
    doc["corrections"], doc["reversed"] = corrections, reversed_days
    return changed


def stamp(doc, now):
    doc["units"] = "levels in m OD Poolbeg, flows in m3/s; one reading a day at 09:00 Irish time; times here are UTC"
    doc["source"] = "ESB hydrometric information, esb.ie/what-we-do/generation-and-trading/hydrometric-information (chart PDFs under " + BASE + ")"
    doc["note"] = ("The ESB do not guarantee these figures. Untested experiment, not an aid to navigation. "
                   "\"corrections\" lists days held differently from the ESB's files; \"reversed\" lists mornings where Pier Head reads above Portumna.")
    doc["updated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")


def save(doc, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def fetch(name):
    req = urllib.request.Request(BASE + name, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--parse":
        g = GAUGES[sys.argv[2]]
        found = readings(open(sys.argv[3], "rb").read(), g["value"])
        for t in sorted(found):
            print(t, "%.2f" % found[t])
        print(len(found), "readings")
        check(found, datetime.datetime.now(datetime.timezone.utc), g)
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--recheck":
        doc = json.load(open(sys.argv[2], encoding="utf-8"))
        changed = False
        for key in PAIR:
            days = history(doc, key)
            before = dict(days)
            correct(key, days)
            if days != before:
                ts = sorted(days)
                doc[key]["history"] = [{"t": t, "v": days[t]} for t in ts]
                doc[key]["level"] = days[ts[-1]]
                changed = True
        changed = crosscheck(doc) or changed
        if changed:
            stamp(doc, datetime.datetime.now(datetime.timezone.utc))
            save(doc, sys.argv[2])
        print("changed" if changed else "nothing to change")
        return 0
    if len(sys.argv) != 2:
        print("usage: update_esb.py esb.json", file=sys.stderr)
        return 2
    path = sys.argv[1]
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    now = datetime.datetime.now(datetime.timezone.utc)
    failed, changed = [], False
    for key, g in GAUGES.items():
        try:
            found = readings(fetch(g["file"]), g["value"])
            check(found, now, g)
        except Exception as e:  # leave this gauge as it was
            failed.append("%s: %s" % (g["name"], e))
            continue
        old = doc.get(key) or {}
        days = history(doc, key)
        days.update(found)  # the ESB's latest figure for a day wins
        correct(key, days)  # except a day known to be the wrong way round
        ts = sorted(days)
        new = {"name": g["name"], "file": g["file"], g["field"]: days[ts[-1]], "time": ts[-1],
               "history": [{"t": t, "v": days[t]} for t in ts]}
        if new != old:
            doc[key] = new
            changed = True
        print("%s: %d days held, newest %s %.2f" % (g["name"], len(ts), ts[-1], days[ts[-1]]))
    changed = crosscheck(doc) or changed
    if changed:
        stamp(doc, now)
        save(doc, path)
    for line in failed:
        print("FAILED " + line, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
