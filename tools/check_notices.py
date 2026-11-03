# Check Waterways Ireland's marine notices list for new notices, once an hour at most.
# Usage: check_notices.py <notices_site.json>
#
# Waterways Ireland's Inspector of Navigation gave written permission (letter received 3 Nov 2026) for this page to read
# their marine notices list no more than once per hour. So this script:
# - makes exactly one request per run, to the marine notices list page only (never the individual notices),
# - refuses to run again within 60 minutes of the last check (the time is kept in notices_site.json),
# - identifies itself by name, with the page's address, so their web team can recognise or block it,
# - keeps only each notice's number, official title and link: nothing is republished in full.
# The page uses it to flag a notice that is on their site but hasn't reached us by email.
import html, json, os, re, ssl, subprocess, sys, tempfile, urllib.error, urllib.request
from datetime import datetime, timezone, timedelta

LIST = "https://www.waterwaysireland.org/news?tabId=tabbedsection&tabName=marinenotices"
BASE = "https://www.waterwaysireland.org"
UA = {"User-Agent": "shannon-almanac-notices/1.0 (hourly marine notices check, by permission; +https://leehughes.ie)",
      "Accept": "text/html"}
MIN_GAP = timedelta(minutes=60)
HOST = "www.waterwaysireland.org"
# Their server doesn't send its intermediate certificate, so it is fetched once from the certificate
# authority (the address named in the site's own certificate) and kept here for later runs.
CA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wi_intermediate.pem")
KEEP = 60

def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))

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

def get_page():
    req = urllib.request.Request(LIST, headers=UA)
    try:
        return urllib.request.urlopen(req, timeout=60, context=context()).read()
    except urllib.error.URLError as e:
        # A failed certificate check stops before any request is sent, so one retry still makes one request.
        if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise
    fetch_intermediate()
    return urllib.request.urlopen(req, timeout=60, context=context()).read()

def parse(page):
    """Marine notice links on the list page: [{no, year, update, title, url}], newest first as listed."""
    out, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href="([^"#]*marine-notice[^"#]*)"[^>]*>(.*?)</a>', page, re.S | re.I):
        href, inner = m.group(1), m.group(2)
        url = href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href
        if not url.startswith(BASE + "/news/"):
            continue
        slug = url.rsplit("/", 1)[-1].lower()
        n = re.search(r"no-?(\d{1,4})-(?:of-)?(\d{4})", slug)
        if not n:
            continue
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        if not title or title.lower() in ("read more", "more", "view"):
            title = ""
        key = url
        if key in seen:
            # The same link can appear twice (a picture and a heading); keep the one with a title.
            for o in out:
                if o["url"] == url and not o["title"] and title:
                    o["title"] = title[:160]
            continue
        seen.add(key)
        out.append({"no": n.group(1).lstrip("0") or "0", "year": n.group(2), "update": slug.startswith(("update", "amend", "cancel", "extension")),
                    "special": "special" in slug, "title": title[:160], "url": url})
    return out

def main(path):
    now = datetime.now(timezone.utc)
    try:
        old = json.load(open(path))
    except Exception:
        old = {}
    last = old.get("checked")
    if last and now - ts(last) < MIN_GAP:
        print(f"Last checked {last}, under an hour ago: not checking again.")
        return
    data = {"checked": iso(now), "source": LIST, "items": old.get("items", [])}
    try:
        page = get_page().decode("utf-8", "replace")
        found = parse(page)
        print(f"Fetched list page: {len(page)} bytes, {len(found)} marine notice links.")
        if not found:
            raise ValueError("no marine notice links found on the list page")
        prev = {i["url"]: i for i in data["items"]}
        # The first list read is the baseline: those notices were already out, so the page doesn't flag them as new.
        baseline = not prev
        items = []
        for f in found:
            p = prev.get(f["url"])
            f["firstSeen"] = p["firstSeen"] if p else iso(now)
            if baseline or (p and p.get("baseline")):
                f["baseline"] = True
            if p and not f["title"]:
                f["title"] = p.get("title", "")
            items.append(f)
        # Keep anything seen before that has dropped off the list page, for a while, below the current ones.
        urls = {i["url"] for i in items}
        items += [p for p in data["items"] if p["url"] not in urls]
        data["items"] = items[:KEEP]
        data["ok"] = True
        new = [f for f in found if f["url"] not in prev]
        for f in new[:10]:
            print("New:", f["no"], f["year"], "(update)" if f["update"] else "", f["title"][:80])
    except Exception as e:
        data["ok"] = False
        data["error"] = str(e)[:200]
        print("Check failed:", e)
    json.dump(data, open(path, "w"), ensure_ascii=False, indent=0)

if __name__ == "__main__":
    main(sys.argv[1])
