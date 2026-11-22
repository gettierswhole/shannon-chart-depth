# Compare Waterways Ireland's notices list (notices_site.json) with the page's summarised notices.
# Usage: notices_gap.py <notices_site.json> <notices live document .json> <state .json or -> [<handled .json or ->]
#   state:   what this script printed as "state" last time ({"alerted": [...], "seen": {...}}), or - if there is none
#   handled: {"<email message id>": "<email date, ISO 8601>", ...} for the emails dealt with in this run, or -
# Prints one JSON object:
#   unsummarised: Shannon notices on their list with no summary on the page (number, their title, link, hours waiting)
#   delisted:     summarised notices that have gone from their list since our summary was written
#   alert:        short lines to tell the owner about, each only once (6 hours' grace for a missing summary)
#   state:        what to store for next time, so nothing is alerted twice and no email is read twice
#                 (seen = the message ids already dealt with, kept for 30 days)
# It reads two local files and writes nothing. No network.
import json, sys
import os
from datetime import datetime, timezone, timedelta

def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def doc(path):
    try:
        d = json.load(open(path))
    except Exception:
        return {}
    return d.get("data", d) if isinstance(d, dict) and "data" in d and "version" in d else d

site, live = doc(sys.argv[1]), doc(sys.argv[2])
state = doc(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else {}
handled = doc(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] != "-" else {}
now = ts(os.environ["GAP_NOW"]) if os.environ.get("GAP_NOW") else datetime.now(timezone.utc)
items = [i for i in site.get("items", []) if isinstance(i, dict) and i.get("url")]
notices = [n for n in live.get("notices", []) if isinstance(n, dict) and n.get("no")]
known = {str(n["no"]): n for n in notices}
GRACE_H, RECENT_DAYS = 6, 21

uns, gone = [], []
for i in items:
    if i.get("special") or i.get("update") or i.get("baseline") or not i.get("shannon") or not i.get("firstSeen"):
        continue
    age = (now - ts(i["firstSeen"])).total_seconds() / 3600
    on_list = i.get("listed") is True or ("listed" not in i and age < RECENT_DAYS * 24)
    if on_list and str(i.get("no")) not in known:
        uns.append({"no": str(i["no"]), "title": i.get("title", ""), "detail": (i.get("detail") or "")[:120],
                    "url": i["url"], "firstSeen": i["firstSeen"], "hours": round(age, 1)})
for n in notices:
    mine = [i for i in items if str(i.get("no")) == str(n["no"]) and not i.get("special")]
    if not mine or any(i.get("listed") is not False for i in mine):
        continue
    when = max((i.get("delisted") or "" for i in mine), default="")
    if when and (not n.get("sent") or ts(when) > ts(n["sent"])) and not n.get("ended"):
        gone.append({"no": str(n["no"]), "title": n.get("title", ""), "delisted": when})

told = set(state.get("alerted", []))
alert = []
for u in uns:
    key = "new-" + u["no"]
    if u["hours"] >= GRACE_H and key not in told:
        alert.append("Marine Notice %s is on Waterways Ireland's list (%s) but no email has come in %d hours." % (u["no"], u["detail"] or u["title"], u["hours"]))
        told.add(key)
for g in gone:
    key = "gone-" + g["no"]
    if key not in told:
        alert.append("Marine Notice %s (%s) is no longer on Waterways Ireland's list. It may have been lifted." % (g["no"], g["title"]))
        told.add(key)
# Forget keys for notices that are no longer in either place.
live_keys = {"new-" + u["no"] for u in uns} | {"gone-" + g["no"] for g in gone}
seen = {}
for src in (state.get("seen"), handled):
    if isinstance(src, dict):
        for k, v in src.items():
            try:
                if now - ts(str(v)) < timedelta(days=30):
                    seen[str(k)] = str(v)
            except Exception:
                pass
print(json.dumps({"siteChecked": site.get("checked"), "siteOk": site.get("ok"), "unsummarised": uns, "delisted": gone,
                  "alert": alert, "state": {"alerted": sorted(told & live_keys), "seen": seen}}, ensure_ascii=False))
