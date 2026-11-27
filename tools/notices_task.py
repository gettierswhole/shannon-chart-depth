# The fixed part of the "Shannon notices check" task. It reads local files and writes local files. No network.
#
# Waterways Ireland's list of live notices (notices_site.json, written by tools/check_notices.py) is the authority.
# The page shows a short summary of each Shannon notice on it, written by the task from their own text, with a link
# to their notice. A notice that is not on their list is not kept: its entry is deleted (owner's decision, 27 Nov
# 2026). So the page's own notices document (notices/live) holds only: one summary per listed notice (src "site",
# with the hash of the text it was written from, or a plain entry the owner wrote on the panel), lock closure days
# taken from listed notices, and entries the owner added by hand under a number of his own (M1 and so on).
# A notice that comes by email and is not on their list is not put on the page: the owner is told once, that is all.
# This script decides, the same way every time, what goes into that document, what the owner is told, and what is
# remembered. The task only writes summaries and picks out facts.
#
#   notices_task.py toread <site.json> <live.json> <state.json or ->
#       Prints a JSON list of the Shannon notices on their list that have no summary of their present text:
#       [{no, title, heading, posted, url, text}]. The task summarises each and reads it for whole-day closures.
#
# A plain entry for a notice that is on their list (one with no src: an earlier summary, or one the owner wrote or
# edited on the Controls panel) stands as that notice's summary and is not written over, until their text changes.
# The state remembers the text each such entry was seen against ("pinned").
#
#   notices_task.py merge <site.json> <live.json> <state.json or -> <extracted.json or -> <out dir>
#       extracted.json, written by the task:
#         {"summaries": [{"url", "title", "text", "until"}],                       one for each notice from toread
#          "emails":   [{"id", "no", "sent", "title", "text", "until", "level"}],   Shannon notice emails not seen before
#          "handled":  {"<email message id>": "<email time, ISO 8601 UTC>"},       every email looked at this run
#          "closures": [{"date", "why", "notice", "url"}],                          whole days locks or bridges are shut
#          "cancelled": ["YYYY-MM-DD"]}                                             closure days a later notice calls off
#       Writes <out dir>/live.json (the new notices document) and <out dir>/state.json, and prints one JSON object:
#         changed (whether live.json differs from what was read), alert (lines to push to the owner, each only once),
#         summary (plain facts for the run report), feeds (times for the run report).
import json, os, re, sys
from datetime import datetime, timezone, timedelta

LIST = "https://www.waterwaysireland.org/news?tabId=tabbedsection&tabName=marinenotices"
WI = "https://www.waterwaysireland.org/"
HOLD = timedelta(hours=72)

def ts(s): return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def doc(path):
    if not path or path == "-":
        return {}
    try:
        d = json.load(open(path))
    except Exception:
        return {}
    return d.get("data", d) if isinstance(d, dict) and "data" in d and "version" in d else d
def irish_day(d):
    try:
        from zoneinfo import ZoneInfo
        return d.astimezone(ZoneInfo("Europe/Dublin")).strftime("%Y-%m-%d")
    except Exception:
        return d.astimezone(timezone.utc).strftime("%Y-%m-%d")
def card(i): return "|".join([i.get("title") or "", i.get("heading") or "", i.get("posted") or ""])
def label(i): return ("Special MN " if i.get("special") else "Update to MN " if i.get("update") else "MN ") + str(i.get("no")) + (", " + i["heading"] if i.get("heading") else "")
def key(i): return ("S" if i.get("special") else "") + str(i.get("no"))

def shannon_items(site):
    return [i for i in site.get("items", []) if isinstance(i, dict) and i.get("url") and i.get("shannon")]

def site_entries(notices):
    return {n.get("url"): n for n in notices if isinstance(n, dict) and n.get("src") == "site" and n.get("url")}

def plain_numbers(notices):
    """Numbers of the plain entries: no src, not ended, a notice number. The owner's or an earlier summary."""
    return {str(n.get("no")) for n in notices if isinstance(n, dict) and not n.get("src") and not n.get("ended")
            and re.fullmatch(r"\d+", str(n.get("no") or ""))}

def stands(i, plain, pinned):
    """True if a plain entry is this notice's summary and their text has not changed since it was first seen with it."""
    if i.get("special") or str(i.get("no")) not in plain:
        return False
    pin = pinned.get(i["url"])
    return not pin or not i.get("textHash") or pin == i["textHash"]

def toread(site, live, state):
    notices = live.get("notices", [])
    have, plain, pinned = site_entries(notices), plain_numbers(notices), state.get("pinned") or {}
    out = []
    for i in shannon_items(site):
        if i.get("listed") is True and i.get("text") and not stands(i, plain, pinned) and (have.get(i["url"]) or {}).get("hash") != i.get("textHash"):
            out.append({k: i.get(k) for k in ("no", "title", "heading", "posted", "url", "text")})
    return out

def merge(site, live, state, ext, now):
    today = irish_day(now)
    items = shannon_items(site)
    listed = {}
    for i in items:
        if i.get("listed") is True and (key(i) not in listed or (i.get("posted") or "") > (listed[key(i)].get("posted") or "")):
            listed[key(i)] = i
    first_run = "known" not in state
    known = dict(state.get("known") or {})
    told = list(state.get("alerted") or [])
    alert, facts = [], []
    def once(k, line):
        """Tell the owner a thing once. True if this is the first time."""
        if k in told:
            return False
        told.append(k)
        if line: alert.append(line)
        return True

    # ----- their list: new, changed, gone -----
    for i in items:
        u, k = i["url"], known.get(i["url"])
        if i.get("listed") is True:
            h, c = i.get("textHash") or "", card(i)
            if k is None:
                if not first_run:
                    if once("new-" + u, ("CLOSURE OR RESTRICTION. " if i.get("kind") == "restriction" else "") +
                            "New on Waterways Ireland's list: %s (posted %s)." % (label(i), i.get("posted") or "date not given")):
                        facts.append("new on their list: " + str(i.get("no")))
            elif k.get("card") != c or (k.get("hash") and h and k["hash"] != h):
                if once("chg-" + u + "-" + (h or c)[:24], "Changed on Waterways Ireland's list: %s." % label(i)):
                    facts.append("changed on their list: " + str(i.get("no")))
            known[u] = {"card": c, "hash": h or (k or {}).get("hash", "")}
        elif i.get("listed") is False and i.get("delisted"):
            if key(i) in listed:
                continue
            if first_run or now - ts(i["delisted"]) > timedelta(days=7):
                once("gone-" + u, None)
            else:
                if once("gone-" + u, "%s is no longer on Waterways Ireland's list of live notices and has been deleted from the page." % label(i)):
                    facts.append("gone from their list: " + str(i.get("no")))
    for u in list(known):
        if not any(i["url"] == u for i in items):
            del known[u]

    # ----- the page's own document -----
    notices = [dict(n) for n in live.get("notices", []) if isinstance(n, dict) and n.get("no")]
    mail_only = []
    for e in ext.get("emails") or []:
        try:
            no, sent = str(e["no"]).strip(), ts(e["sent"])
            if not re.fullmatch(r"\d{1,4}", no) or not e.get("title") or not e.get("text"):
                continue
        except Exception:
            continue
        on_list = listed.get(no)
        if on_list and (on_list.get("posted") or "") >= irish_day(sent):
            continue   # their list already shows it: the page has their words
        mail_only.append(no)
        if once("mail-%s-%s" % (no, iso(sent)), "By email, not on Waterways Ireland's list (so not on the page): MN %s, %s." % (no, str(e["title"])[:90])):
            facts.append("by email only, owner told: " + no)
    # Summaries the task wrote this run, each tied to the text it was written from.
    by_url = {i["url"]: i for i in items if i.get("listed") is True}
    pinned = {u: v for u, v in (state.get("pinned") or {}).items() if u in by_url}
    plain = plain_numbers(notices)
    for s in ext.get("summaries") or []:
        i = by_url.get(str(s.get("url") or "")) if isinstance(s, dict) else None
        if not i or not i.get("text") or not s.get("title") or not s.get("text") or stands(i, plain, pinned):
            continue
        until = s.get("until") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.get("until") or "")) else "2099-12-31"
        notices = [n for n in notices if not (n.get("src") == "site" and n.get("url") == i["url"])]
        notices.append({"no": str(i.get("no")), "src": "site", "url": i["url"], "title": str(s["title"])[:90], "text": str(s["text"])[:400],
                        "hash": i.get("textHash"), "posted": i.get("posted"), "until": until, "level": ""})
        facts.append("summary written: " + str(i.get("no")))
    have = site_entries(notices)
    # Where a plain entry stands as a notice's summary, a summary written by the task for the same notice gives way.
    notices = [n for n in notices if not (n.get("src") == "site" and n.get("url") in by_url and stands(by_url[n["url"]], plain, pinned))]
    have = site_entries(notices)
    # What stays: a summary of a notice that is on their list (or missed by one read only), and the owner's own entries.
    held = {i["url"] for i in items if not i.get("delisted")}
    held_no = {key(i) for i in items if not i.get("delisted") and not i.get("special")}
    kept = []
    for n in notices:
        no = str(n.get("no"))
        if n.get("src") == "site":
            if n.get("url") in held: kept.append(n)
            continue
        if n.get("src") == "email" or n.get("ended"):
            continue          # not on their list: deleted
        if re.fullmatch(r"\d+", no):
            L = listed.get(no)
            if no not in held_no:
                continue      # not on their list: deleted
            if L:
                if L["url"] in have and not stands(L, plain, pinned):
                    pinned.pop(L["url"], None)
                    continue  # their text changed and a new summary has been written from it
                if not pinned.get(L["url"]):
                    pinned[L["url"]] = L.get("textHash") or ""   # this entry stands as the summary of this text
            kept.append(n)
            continue
        try:                  # the owner's own entry: kept until its last day has passed
            if n.get("until") and n["until"] < today: continue
        except Exception:
            pass
        kept.append(n)
    def order(n):
        t = n.get("ended") or n.get("sent") or ""
        return (0 if t else 1, "" if not t else "".join(chr(255 - ord(c)) for c in t), -(int(n["no"]) if str(n["no"]).isdigit() else 0))
    kept.sort(key=order)

    def closure_ok(c):
        u = str(c.get("url") or "")
        return u == LIST or u in held        # the owner's own (the general link), or from a notice on their list
    closures = [c for c in live.get("closures", []) if isinstance(c, dict) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get("date") or ""))
                and c["date"] >= today and closure_ok(c)]
    for c in ext.get("closures") or []:
        if (isinstance(c, dict) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(c.get("date") or "")) and c["date"] >= today
                and str(c.get("url") or "") in by_url and not any(x["date"] == c["date"] for x in closures)):
            closures.append({"date": c["date"], "why": str(c.get("why") or "")[:60], "notice": str(c.get("notice") or "")[:40], "url": c["url"]})
            facts.append("closure day added: " + c["date"])
    off = {d for d in (ext.get("cancelled") or []) if isinstance(d, str)}
    if off & {c["date"] for c in closures}:
        facts.append("closure days removed: " + ", ".join(sorted(off & {c["date"] for c in closures})))
    closures = sorted([c for c in closures if c["date"] not in off], key=lambda c: c["date"])

    old_cmp = {"notices": live.get("notices", []), "closures": live.get("closures", [])}
    changed = json.dumps({"notices": kept, "closures": closures}, sort_keys=True) != json.dumps(old_cmp, sort_keys=True)
    new_live = dict(live)
    new_live.update(notices=kept, closures=closures)
    if changed: new_live["updated"] = iso(now)

    # ----- is their list being read? -----
    bad = site.get("ok") is False or bool(site.get("suspect"))
    last_good = site.get("lastGood") or (site.get("checked") if not bad else None)
    stale = (not last_good) or now - ts(last_good) > timedelta(hours=3)
    runs_bad = int(state.get("readBad") or 0) + 1 if (bad or stale) else 0
    if runs_bad >= 2:
        once("read-bad", "Waterways Ireland's list of notices has not been read properly since %s (%s). The page may be out of date." % (
            last_good or "it was first set up", site.get("error") or ("the last read looked short" if site.get("suspect") else "no recent read")))
    elif runs_bad == 0 and "read-bad" in told:
        told.remove("read-bad")

    seen = {}
    for src in (state.get("seen"), ext.get("handled")):
        if isinstance(src, dict):
            for k, v in src.items():
                try:
                    if now - ts(v) < timedelta(days=30): seen[str(k)] = str(v)
                except Exception:
                    pass
    new_state = {"v": 2, "alerted": told[-300:], "seen": seen, "known": known, "pinned": pinned, "readBad": runs_bad}
    live_now = [i for i in items if i.get("listed") is True]
    summary = {"siteChecked": site.get("checked"), "siteOk": site.get("ok"), "suspect": bool(site.get("suspect")), "lastGood": last_good,
               "liveShannon": sorted({str(i.get("no")) for i in live_now}, key=lambda s: -int(s) if s.isdigit() else 0),
               "noTextYet": [str(i.get("no")) for i in live_now if not i.get("text")],
               "noSummaryYet": [str(i.get("no")) for i in live_now if (have.get(i["url"]) or {}).get("hash") != (i.get("textHash") or "-") and not stands(i, plain, pinned)],
               "emailOnly": mail_only, "ownEntries": [str(n.get("no")) for n in kept], "closureDays": [c["date"] for c in closures],
               "facts": facts, "firstRun": first_run}
    feeds = [{"name": "Notices: Waterways Ireland's list last read", "at": last_good or site.get("checked"), "limit_h": 9,
              "note": "%d Shannon notices live; %d without a summary yet" % (len(live_now), len(summary["noSummaryYet"]))},
             {"name": "Notices: our own entries last changed", "at": new_live.get("updated")}]
    return new_live, new_state, {"changed": changed, "alert": alert, "summary": summary, "feeds": [f for f in feeds if f.get("at")]}

if __name__ == "__main__":
    now = ts(os.environ["TASK_NOW"]) if os.environ.get("TASK_NOW") else datetime.now(timezone.utc)
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "toread":
        print(json.dumps(toread(doc(sys.argv[2]), doc(sys.argv[3]), doc(sys.argv[4]) if len(sys.argv) > 4 else {}), ensure_ascii=False))
    elif mode == "merge":
        site, live, state, ext, out = doc(sys.argv[2]), doc(sys.argv[3]), doc(sys.argv[4]), doc(sys.argv[5]), sys.argv[6]
        if not isinstance(live.get("notices"), list):
            sys.exit("the notices document could not be read: nothing written")
        os.makedirs(out, exist_ok=True)
        new_live, new_state, result = merge(site, live, state, ext if isinstance(ext, dict) else {}, now)
        json.dump(new_live, open(os.path.join(out, "live.json"), "w"), ensure_ascii=False)
        json.dump(new_state, open(os.path.join(out, "state.json"), "w"), ensure_ascii=False)
        print(json.dumps(result, ensure_ascii=False))
    else:
        sys.exit("usage: notices_task.py toread <site> <live> <state|-> | merge <site> <live> <state|-> <extracted|-> <out dir>")
