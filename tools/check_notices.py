# Read Waterways Ireland's list of live marine notices, and the text of the Shannon ones, once an hour at most.
# Usage: check_notices.py <notices_site.json>
#
# Waterways Ireland's Inspector of Navigation gave written permission (letter received 3 Nov 2026) for this page to
# read their marine notices no more than once per hour, and on 24 Nov 2026 told the owner the notices may be read
# and shown freely. Their list page says "only live marine notices are displayed", so the list is the authority:
# a notice is shown because it is on the list, and is deleted when it is not (owner's decision, 27 Nov 2026).
#
# One visit, at least 60 minutes after the last:
# - one request for the list page (it holds every live notice, including the cards hidden for "page 2"),
# - then the page of each Shannon notice that is new, whose card has changed, or that has no text yet
#   (at most MAX_PAGES a visit, 2 seconds apart), or failing that one re-read of the text checked longest ago,
#   so an edit that leaves the card unchanged is still caught within a day or so.
# It identifies itself by name, with the page's address, so their web team can recognise or block it.
#
# Each item: no, year, update, special, title (their card title), heading (their card line), posted (YYYY-MM-DD),
# detail (heading + posted, as older page code reads it), url, firstSeen, changed (card or text changed),
# shannon (true unless the heading names only another waterway), kind ("restriction", "relief" or ""),
# listed, and for Shannon notices text (their words, as written), textAt, textHash.
# Leaving the list: the first good read that misses a notice sets listed false, so it is off the page at once.
# The second sets delisted (the time of the first miss) and drops its text; 24 hours later the item is deleted from
# this file. That day is only so the notices task can tell the owner once. A notice that comes back is listed again.
# A read that finds far fewer cards than the last one is marked suspect and takes nothing off the list.
import hashlib, html, json, os, re, ssl, subprocess, sys, tempfile, time, urllib.error, urllib.request
from datetime import datetime, timezone, timedelta

LIST = "https://www.waterwaysireland.org/news?tabId=tabbedsection&tabName=marinenotices"
BASE = "https://www.waterwaysireland.org"
UA = {"User-Agent": "shannon-almanac-notices/2.0 (hourly marine notices check, by permission; +https://leehughes.ie)",
      "Accept": "text/html"}
MIN_GAP = timedelta(minutes=60)      # never two visits inside an hour
WAIT_FROM = timedelta(minutes=45)    # started a little early: wait out the hour instead of skipping
MAX_PAGES = 5                        # notice pages read in one visit
PAUSE = 2                            # seconds between requests in a visit
REFRESH_AFTER = timedelta(hours=24)  # re-read a notice's text when it was last checked longer ago than this
GONE_KEEP = timedelta(hours=24)      # a notice confirmed gone from their list is deleted from the file after this
TEXT_MAX = 8000
KEEP = 60
HOST = "www.waterwaysireland.org"
TEST = os.environ.get("NOTICES_TEST_DIR")   # tests only: read pages from files, never the network
# Their server doesn't send its intermediate certificate, so it is fetched once from the certificate
# authority (the address named in the site's own certificate) and kept here for later runs.
CA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wi_intermediate.pem")

SHANNON_ERNE = re.compile(r"shannon\s*[-–—]\s*erne(\s+waterway)?", re.I)
NAMES_IN = re.compile(r"shannon|all navigations|all waterway|lough (derg|ree|key|allen|boderg|bofin|forbes)|ardnacrusha|killaloe|"
                      r"portumna|banagher|athlone|lanesborough|tarmonbarry|termonbarry|roosk|carrick|boyle|leitrim|meelick|"
                      r"shannonbridge|dromod|jamestown|drumsna|scarriff|dromineer|limerick|clondra|camlin|victoria lock|"
                      r"albert lock|clarendon|knockvicar|cootehall|battlebridge|drumshanbo", re.I)
NAMES_OUT = re.compile(r"grand canal|royal canal|canal navigations|barrow|\berne\b|\bbann\b|lagan|ulster canal", re.I)
RELIEF = re.compile(r"re-?open|operational|lifted|cancel|restored|resum|repairs? complete|back in operation", re.I)
RESTRICT = re.compile(r"clos|restrict|industrial action|not operat|suspen|out of service|fault|obstruct|sunk|block|"
                      r"impassable|no passage|hazard|danger", re.I)

def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", s, flags=re.S | re.I))).strip()

def shannonish(title, heading):
    """True unless the card names only another waterway. A notice that names no waterway is let in."""
    text = (title or "") + " " + (heading or "")
    if NAMES_IN.search(SHANNON_ERNE.sub(" ", text)):
        return True
    return not (NAMES_OUT.search(text) or SHANNON_ERNE.search(text))

def kind(title, heading):
    text = (title or "") + " " + (heading or "")
    if RELIEF.search(text):
        return "relief"
    return "restriction" if RESTRICT.search(text) else ""

def old_heading(p):
    """The card line of an item stored by the earlier version of this script (it kept 'heading Posted: date ...')."""
    if p.get("heading") is not None:
        return p["heading"]
    return re.sub(r"\s*Posted:.*$", "", p.get("detail") or "", flags=re.S).strip()

def old_posted(p):
    if p.get("posted"):
        return p["posted"]
    m = re.search(r"Posted:\s*(\d{1,2})/(\d{1,2})/(\d{4})", p.get("detail") or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None

# ---------- fetching ----------
def context():
    c = ssl.create_default_context()
    if os.path.exists(CA_FILE):
        c.load_verify_locations(CA_FILE)
    return c

def fetch_intermediate():
    """Get the missing intermediate certificate from the issuer address in the site's certificate."""
    leaf = ssl.get_server_certificate((HOST, 443))
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(leaf)
    text = subprocess.run(["openssl", "x509", "-in", f.name, "-noout", "-text"], capture_output=True, text=True).stdout
    m = re.search(r"CA Issuers - URI:(\S+)", text)
    if not m:
        raise ValueError("site certificate names no issuer address")
    raw = urllib.request.urlopen(urllib.request.Request(m.group(1), headers={"User-Agent": UA["User-Agent"]}), timeout=30).read()
    if b"BEGIN CERTIFICATE" in raw:
        pem = raw.decode()
    else:
        pem = subprocess.run(["openssl", "x509", "-inform", "DER", "-outform", "PEM"], input=raw, capture_output=True).stdout.decode()
    if "BEGIN CERTIFICATE" not in pem:
        raise ValueError("could not read the intermediate certificate")
    open(CA_FILE, "w").write(pem)
    print("Saved the intermediate certificate from", m.group(1))

def get_page(url):
    """One request. Returns the page text. Raises if the site answers with its not-found page."""
    if not (url == LIST or url.startswith(BASE + "/news/")):
        raise ValueError("not a marine notices address: " + url[:80])
    if TEST:
        name = "list.html" if url == LIST else url.rsplit("/", 1)[-1] + ".html"
        path = os.path.join(TEST, name)
        if not os.path.exists(path):
            path = os.path.join(TEST, "notice.html")
        if url != LIST and os.path.exists(os.path.join(TEST, "missing-" + name)):
            raise ValueError("page not found")
        return open(path, encoding="utf-8").read()
    req = urllib.request.Request(url, headers=UA)
    def go():
        r = urllib.request.urlopen(req, timeout=60, context=context())
        if "page-not-found" in (r.geturl() or ""):
            raise ValueError("page not found")
        return r.read().decode("utf-8", "replace")
    try:
        return go()
    except urllib.error.HTTPError as e:
        raise ValueError("page not found" if e.code in (404, 410) else f"HTTP {e.code}")
    except urllib.error.URLError as e:
        # A failed certificate check stops before any request is sent, so one retry still makes one request.
        if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise
    fetch_intermediate()
    return go()

# ---------- the list ----------
CARD = re.compile(r'<li\b[^>]*>\s*<article\b[^>]*class="[^"]*wi-document-card[^"]*"[^>]*>(.*?)</article>\s*</li>', re.S | re.I)

def number(title, slug):
    m = (re.search(r"No\.?\s*(\d{1,4})", title, re.I) or re.search(r"Notice\s+(\d{1,4})\b", title, re.I)
         or re.search(r"(?:no-?)?(\d{1,4})-(?:of-)?20\d{2}", slug))
    y = re.search(r"(20\d{2})", title) or re.search(r"(20\d{2})", slug)
    return (m.group(1).lstrip("0") or "0") if m else "", y.group(1) if y else ""

def parse_list(page):
    """Every marine notice card on the list page, as listed (newest first): the 12 shown and those hidden for page 2."""
    out, seen = [], set()
    for m in CARD.finditer(page):
        c = m.group(1)
        a = re.search(r'<a\b[^>]*href="([^"#]+)"', c, re.I)
        h3 = re.search(r"<h3\b[^>]*>(.*?)</h3>", c, re.S | re.I)
        if not a:
            continue
        href = html.unescape(a.group(1))
        url = href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href
        title = clean(h3.group(1)) if h3 else ""
        slug = url.rsplit("/", 1)[-1].lower()
        if not url.startswith(BASE + "/news/") or not re.search(r"marine[\s-]*notice", title + " " + slug, re.I) or url in seen:
            continue
        seen.add(url)
        p = re.search(r'<p\b[^>]*class="wi-document-card__text"[^>]*>(.*?)</p>', c, re.S | re.I)
        t = re.search(r'<time\b[^>]*datetime="(\d{4}-\d{2}-\d{2})', c, re.I)
        heading = clean(p.group(1))[:200] if p else ""
        posted = t.group(1) if t else None
        no, year = number(title, slug)
        upd = ("update", "amend", "cancel", "extension")
        item = {"no": no, "year": year, "update": slug.startswith(upd) or title.lower().startswith(upd),
                "special": "special" in slug or "special" in title.lower(), "title": title[:160], "heading": heading,
                "posted": posted, "url": url}
        item["detail"] = (heading + (" Posted: %s/%s/%s" % (posted[8:10], posted[5:7], posted[0:4]) if posted else "")).strip()
        out.append(item)
    return out

# ---------- a notice page ----------
def parse_notice(page):
    """Their words, as written: the article body of a notice page, as plain text with its line breaks."""
    m = re.search(r'itemprop="articleBody"[^>]*>(.*?)</article>', page, re.S | re.I)
    if not m:
        raise ValueError("no article body on the notice page")
    b = re.sub(r"<(script|style)\b.*?</\1>", " ", m.group(1), flags=re.S | re.I)
    b = re.sub(r"[\r\n\t]+", " ", b)
    b = re.sub(r"<br\s*/?>", "\n", b, flags=re.I)
    b = re.sub(r"</t[dh]>", " | ", b, flags=re.I)
    b = re.sub(r"<li\b[^>]*>", "\n• ", b, flags=re.I)
    b = re.sub(r"</(p|div|li|h[1-6]|tr|ul|ol|table|blockquote)>", "\n\n", b, flags=re.I)
    b = html.unescape(re.sub(r"<[^>]+>", "", b)).replace("\xa0", " ")
    lines = [re.sub(r" +", " ", l).strip(" |") if set(l.strip()) <= set(" |") else re.sub(r" +", " ", l).strip() for l in b.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text) < 40:
        raise ValueError("notice text too short to be the notice")
    h1 = re.search(r'<h1\b[^>]*>(.*?)</h1>', page, re.S | re.I)
    cut = len(text) > TEXT_MAX
    return {"text": text[:TEXT_MAX], "cut": cut, "pageHeading": clean(h1.group(1))[:200] if h1 else ""}

def read_text(i, now, why):
    """Read one notice's page and store its text on the item. Returns True if a request was made."""
    i["textTried"] = iso(now)
    try:
        got = parse_notice(get_page(i["url"]))
    except Exception as e:
        i["textTries"] = int(i.get("textTries", 0)) + 1
        i["textError"] = str(e)[:120]
        print("Text not read:", i["no"], why, "|", i["textError"])
        return True
    h = hashlib.sha256(got["text"].encode()).hexdigest()[:16]
    if i.get("textHash") and i["textHash"] != h:
        i["changed"] = iso(now)
        i["textChanged"] = iso(now)
        print("Text changed:", i["no"], i["title"][:60])
    i.update(text=got["text"], textHash=h, textAt=iso(now))
    if got["cut"]: i["textCut"] = True
    else: i.pop("textCut", None)
    if got["pageHeading"]: i["pageHeading"] = got["pageHeading"]
    i.pop("textTries", None); i.pop("textError", None)
    print("Text read:", i["no"], why, "|", len(got["text"]), "characters")
    return True

def main(path):
    now = datetime.now(timezone.utc)
    try:
        old = json.load(open(path))
    except Exception:
        old = {}
    last = old.get("checked")
    if last and not TEST:
        gap = now - ts(last)
        if gap < WAIT_FROM:
            print(f"Last visit {last}, under 45 minutes ago: not visiting again.")
            return
        if gap < MIN_GAP:
            wait = (MIN_GAP - gap).total_seconds() + 5
            print(f"Last visit {last}: waiting {int(wait)} s so the visits are an hour apart.")
            time.sleep(wait)
            now = datetime.now(timezone.utc)
    data = {"v": 2, "checked": iso(now), "source": LIST, "items": old.get("items", [])}
    for k in ("lastGood", "count"):
        if k in old: data[k] = old[k]
    try:
        page = get_page(LIST)
        found = parse_list(page)
        print(f"Fetched list page: {len(page)} bytes, {len(found)} marine notice cards.")
        if not found:
            raise ValueError("no marine notice cards found on the list page")
        prev = {i["url"]: i for i in data["items"]}
        was_listed = [i for i in data["items"] if i.get("listed") is True]
        gone_now = [i for i in was_listed if i["url"] not in {f["url"] for f in found}]
        # A short read (a broken or half-loaded page) must not take notices down.
        suspect = bool(was_listed) and (len(found) < max(4, 0.6 * len(was_listed)) or len(gone_now) > 4)
        data["liveNote"] = bool(re.search(r"only live marine notices are displayed", page, re.I))
        baseline = not prev
        items = []
        for f in found:
            p = prev.get(f["url"])
            f["firstSeen"] = p["firstSeen"] if p else iso(now)
            if p and (p.get("title", "") != f["title"] or old_heading(p) != f["heading"] or (old_posted(p) and f["posted"] and old_posted(p) != f["posted"])):
                f["changed"] = iso(now)
                f["cardChanged"] = iso(now)
                print("Card changed:", f["no"], f["title"][:60], "|", f["heading"][:60])
            elif p:
                for k in ("changed", "cardChanged"):
                    if p.get(k): f[k] = p[k]
            if baseline or (p and p.get("baseline")):
                f["baseline"] = True
            if p:
                for k in ("text", "textHash", "textAt", "textCut", "textTries", "textTried", "textError", "textChanged", "pageHeading"):
                    if k in p: f[k] = p[k]
            f["listed"] = True   # on the list now: any earlier miss is forgotten
            f["shannon"] = shannonish(f["title"], f["heading"])
            f["kind"] = kind(f["title"], f["heading"])
            if not f["shannon"]:
                for k in ("text", "textHash", "textAt", "textCut", "pageHeading"): f.pop(k, None)
            items.append(f)
        # Anything seen before that is not on the list now.
        urls = {i["url"] for i in items}
        for p in data["items"]:
            if p["url"] in urls:
                continue
            p = dict(p)
            p.setdefault("heading", old_heading(p))
            if not p.get("posted") and old_posted(p): p["posted"] = old_posted(p)
            p["shannon"] = shannonish(p.get("title"), p.get("heading"))
            p["kind"] = kind(p.get("title"), p.get("heading"))
            if not suspect and not p.get("delisted"):
                if p.get("listed") is True:
                    p.update(listed=False, missed=1, missedSince=iso(now))     # off the page at once
                    print("Missing from the list:", p["no"], p.get("title", "")[:60])
                elif p.get("missedSince"):
                    p["delisted"] = p.pop("missedSince")                       # missed twice: gone
                    p.pop("missed", None)
                    print("Off the list:", p["no"], p.get("title", "")[:60])
            if p.get("delisted"):
                if now - ts(p["delisted"]) > GONE_KEEP:
                    print("Deleted:", p["no"], p.get("title", "")[:60])
                    continue
                for k in ("text", "textHash", "textAt", "textCut", "pageHeading", "textTries", "textTried", "textError", "textChanged"): p.pop(k, None)
            items.append(p)
        data["items"] = items[:KEEP]
        data["count"] = len(found)
        data["ok"] = True
        if suspect:
            data["suspect"] = True
            print(f"Suspect read: {len(found)} cards against {len(was_listed)} listed before. Nothing taken off the list.")
        else:
            data["lastGood"] = iso(now)
        # Their words: the pages of Shannon notices that are new, changed, or not read yet; else one refresh.
        live = [i for i in data["items"] if i.get("listed") is True and i.get("shannon")]
        def needs(i):
            if not i.get("text"):
                tried = i.get("textTried")
                return int(i.get("textTries", 0)) < 3 or not tried or (i.get("cardChanged") and i["cardChanged"] > tried)
            return bool(i.get("cardChanged") and i["cardChanged"] > i.get("textAt", ""))
        todo = sorted([i for i in live if needs(i)], key=lambda i: i.get("posted") or "", reverse=True)[:MAX_PAGES]
        why = "new or changed"
        if not todo:
            stale = sorted([i for i in live if i.get("text") and now - ts(i["textAt"]) > REFRESH_AFTER], key=lambda i: i["textAt"])
            todo, why = stale[:1], "daily re-read"
        for i in todo:
            if not TEST: time.sleep(PAUSE)
            read_text(i, datetime.now(timezone.utc), why)
        print("Shannon notices live:", ", ".join(i["no"] + ("" if i.get("text") else " (no text yet)") for i in live))
        for f in [f for f in found if f["url"] not in prev][:10]:
            print("New:", f["no"], f["year"], "(update)" if f["update"] else "", f["title"][:60], "|", f["heading"][:60])
    except Exception as e:
        data["ok"] = False
        data["error"] = str(e)[:200]
        print("Check failed:", e)
    json.dump(data, open(path, "w"), ensure_ascii=False, indent=0)

if __name__ == "__main__":
    main(sys.argv[1])
