# Reads the ESB's daily 09:00 levels for Lough Derg (Pier Head, Killaloe and Portumna Bridge) from the
# chart PDFs the ESB publish, and writes them to esb.json.
#
# Why: the Lough Derg chart datum is set at Killaloe, but the page's live gauge is at Portumna, at the other
# end of the lake. Pier Head shows the Killaloe end. See claude/esb-pier-head.md in the project notes.
#
# The ESB give one reading a day, in metres over Poolbeg datum, and each file holds about 30 days.
# esb.json keeps every day seen, so the record grows past 30 days.
#
# Nothing is guessed. If a file cannot be fetched or does not read as expected, that gauge is left as it
# was and the script exits with an error, so the run shows as failed.
#
# Usage: python3 tools/update_esb.py esb.json            (fetch and update)
#        python3 tools/update_esb.py --parse file.pdf    (print what a saved PDF holds)
import datetime, json, re, sys, urllib.request, zlib
from zoneinfo import ZoneInfo

BASE = "http://www.esbhydro.ie/Shannon/"
GAUGES = {
    "pierHead": {"file": "06-Pier-Head-Killaloe.pdf", "name": "Pier Head, Killaloe"},
    "portumna": {"file": "05-Portumna-Bridge.pdf", "name": "Portumna Bridge"},
}
AGENT = "shannon-chart-depth (github.com/gettierswhole/shannon-chart-depth)"
DUBLIN = ZoneInfo("Europe/Dublin")
MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
STAMP = re.compile(r"^(\d\d)-([A-Z][a-z]{2})-(\d\d) (\d\d):(\d\d):(\d\d)$")
VALUE = re.compile(r"^\d\d\.\d\d$")
# Lough Derg has stood between 32.0 (statutory minimum) and 34.76 (Portumna, Nov 2009) m Poolbeg.
LOW, HIGH = 31.5, 35.5


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


def readings(pdf):
    """{UTC time: level} from the table of daily readings: a timestamp and a value on the same line."""
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


def check(found, now):
    """Refuse anything that does not look like a month of daily lake levels."""
    if len(found) < 20:
        raise ValueError("only %d readings found; expected about 30" % len(found))
    if not all(LOW < v < HIGH for v in found.values()):
        raise ValueError("a level outside %.1f to %.1f m Poolbeg" % (LOW, HIGH))
    ts = sorted(found)
    newest = datetime.datetime.strptime(ts[-1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    if newest > now + datetime.timedelta(hours=1):
        raise ValueError("newest reading is in the future: " + ts[-1])
    steps = [abs(found[b] - found[a]) for a, b in zip(ts, ts[1:])]
    if max(steps) > 0.6:
        raise ValueError("a jump of %.2f m between days" % max(steps))


def fetch(name):
    req = urllib.request.Request(BASE + name, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--parse":
        found = readings(open(sys.argv[2], "rb").read())
        for t in sorted(found):
            print(t, "%.2f" % found[t])
        print(len(found), "readings")
        check(found, datetime.datetime.now(datetime.timezone.utc))
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
            found = readings(fetch(g["file"]))
            check(found, now)
        except Exception as e:  # leave this gauge as it was
            failed.append("%s: %s" % (g["name"], e))
            continue
        old = doc.get(key) or {}
        days = {p["t"]: p["v"] for p in old.get("history", []) if isinstance(p, dict) and "t" in p and "v" in p}
        days.update(found)  # the ESB's latest figure for a day wins
        ts = sorted(days)
        new = {"name": g["name"], "file": g["file"], "level": days[ts[-1]], "time": ts[-1],
               "history": [{"t": t, "v": days[t]} for t in ts]}
        if new != old:
            doc[key] = new
            changed = True
        print("%s: %d days held, newest %s %.2f m" % (g["name"], len(ts), ts[-1], days[ts[-1]]))
    if changed:
        doc["units"] = "m OD Poolbeg; one reading a day at 09:00 Irish time; times here are UTC"
        doc["source"] = "ESB hydrometric information, esb.ie/what-we-do/generation-and-trading/hydrometric-information (chart PDFs under " + BASE + ")"
        doc["note"] = "The ESB do not guarantee these figures. Untested experiment, not an aid to navigation."
        doc["updated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
    for line in failed:
        print("FAILED " + line, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
