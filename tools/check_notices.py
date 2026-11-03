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
import html, json, re, sys, urllib.request
from datetime import datetime, timezone, timedelta

LIST = "https://www.waterwaysireland.org/news?tabId=tabbedsection&tabName=marinenotices"
BASE = "https://www.waterwaysireland.org"
UA = {"User-Agent": "shannon-almanac-notices/1.0 (hourly marine notices check, by permission; +https://leehughes.ie)",
      "Accept": "text/html"}
MIN_GAP = timedelta(minutes=60)
KEEP = 60

def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))

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
        req = urllib.request.Request(LIST, headers=UA)
        page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        found = parse(page)
        print(f"Fetched list page: {len(page)} bytes, {len(found)} marine notice links.")
        if not found:
            raise ValueError("no marine notice links found on the list page")
        prev = {i["url"]: i for i in data["items"]}
        items = []
        for f in found:
            p = prev.get(f["url"])
            f["firstSeen"] = p["firstSeen"] if p else iso(now)
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
