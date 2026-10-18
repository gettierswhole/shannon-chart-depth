# The site's own record of the Shannon navigation gauges, kept in the repository under archive/.
# No AI in the loop. Run by GitHub Actions (.github/workflows/archive.yml).
#
#   archive_gauges.py log   <archive dir>   Append every 15-minute OPW reading of the last month that the log
#                                           doesn't hold yet to archive/log/YYYY-MM.csv. Readings are written as
#                                           first seen and never rewritten, so the log stays an independent,
#                                           time-stamped record even if OPW later revise or withdraw a value.
#   archive_gauges.py daily <archive dir>   Rebuild the daily-mean history from the start of each gauge's
#                                           published record: shannon_gauges_daily.csv (one column per gauge),
#                                           shannon_gauges_daily_long.csv (with OPW quality codes),
#                                           stations.csv and datum_checks.csv.
#
# Source: OPW Hydro-Data (waterlevel.ie/hydro-data), CC BY 4.0. Levels are in metres as OPW publish them.
import csv, json, os, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://waterlevel.ie/hydro-data/data/internet/stations"
UA = {"User-Agent": "shannon-chart-depth archive (github.com/gettierswhole)"}
# station no, short id (column name), name, waterway / stretch. Upstream first.
STATIONS = [
    ("26074", "blackrock_lock", "Blackrock Lock", "Lough Allen"),
    ("26108", "boyle_abbey", "Boyle Abbey Bridge", "Boyle River (Lough Key)"),
    ("26324", "carrick", "Carrick-on-Shannon", "Upper Shannon"),
    ("26085", "jamestown", "Jamestown", "Upper Shannon"),
    ("26359", "jamestown_weir_us", "Jamestown Weir U/S", "Upper Shannon"),
    ("26401", "jamestown_weir_ds", "Jamestown Weir D/S", "Upper Shannon"),
    ("26089", "drumsna", "Drumsna", "Upper Shannon"),
    ("26093", "derry_bay", "Derry Bay", "Lough Ree"),
    ("26088", "hodsons_bay", "Hodson's Bay", "Lough Ree"),
    ("26333", "athlone_weir_us", "Athlone Weir U/S", "Lough Ree (Athlone)"),
    ("26027", "athlone", "Athlone (below the weir)", "Meelick - Athlone"),
    ("26353", "wops_rail_bridge", "W.O.P.S. Rail Bridge", "Meelick - Athlone"),
    ("26028", "shannonbridge", "Shannonbridge", "Meelick - Athlone"),
    ("26351", "derryholmes_us", "Derryholmes U/S", "Meelick - Athlone"),
    ("26352", "derryholmes_ds", "Derryholmes D/S", "Meelick - Athlone"),
    ("25017", "banagher", "Banagher", "Meelick - Athlone"),
    ("25056", "meelick_weir_us", "Meelick Weir U/S", "Meelick - Athlone"),
    ("25058", "victoria_lock", "Victoria Lock", "Meelick - Portumna"),
    ("26356", "raherbeg_rail_bridge", "Raherbeg Rail Bridge", "River Suck"),
    ("26354", "ballinasloe_town", "Ballinasloe Town", "River Suck"),
    ("26355", "ballinasloe_old_channel", "Ballinasloe Old Channel", "River Suck"),
    ("25341", "portumna", "Portumna Bridge", "Lough Derg (Portumna)"),
]
QUALITY = {31: "inspected", 32: "corrected", 101: "unreliable", 254: "unchecked (provisional)"}
STEP_M = 0.8   # a day-to-day change in daily mean bigger than this is flagged as a possible datum change


def get_json(url, tries=3):
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:
            err = e
        time.sleep(5 * (i + 1))
    raise err


def series(no, name):
    j = get_json(f"{BASE}/0/{no}/S/{name}.json")
    if not j:
        return None, []
    return j[0], j[0].get("data") or []


def iso(d): return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_log(out):
    logdir = os.path.join(out, "log")
    os.makedirs(logdir, exist_ok=True)
    now = datetime.now(timezone.utc)
    have, files = set(), {}
    # Months the new readings can fall in: this one and the one before.
    for m in {(now - timedelta(days=d)).strftime("%Y-%m") for d in (0, 35)}:
        p = os.path.join(logdir, m + ".csv")
        files[m] = p
        if os.path.exists(p):
            with open(p, newline="") as f:
                for r in csv.DictReader(f):
                    have.add((r["station_no"], r["time_utc"]))
    new = {}
    report = []
    for no, sid, name, _ in STATIONS:
        try:
            _, rows = series(no, "month")
        except Exception as e:
            report.append(f"{no} {name}: unavailable ({e})"); continue
        n = 0
        for r in rows:
            if len(r) < 2 or r[1] is None:
                continue
            q = r[2] if len(r) > 2 else None
            if q is not None and int(q) < 0:
                continue
            t = r[0].replace(".000Z", "Z")
            if (no, t) in have:
                continue
            m = t[:7]
            if m not in files:      # older than the previous month: those months are closed
                continue
            new.setdefault(m, []).append([t, no, sid, r[1], q if q is not None else "", iso(now)])
            have.add((no, t)); n += 1
        report.append(f"{no} {name}: {n} new")
    cols = ["time_utc", "station_no", "station", "level_m", "quality", "logged_utc"]
    for m, rows in new.items():
        p = files[m]
        exists = os.path.exists(p)
        rows.sort(key=lambda r: (r[0], r[1]))
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(cols)
            w.writerows(rows)
    print("\n".join(report))


def cmd_daily(out):
    os.makedirs(out, exist_ok=True)
    meta = {}
    try:
        meta = {s["station_no"]: s for s in get_json(f"{BASE}/stations.json") or []}
    except Exception as e:
        print("stations.json unavailable:", e)
    by_station, stations_rows, checks = {}, [], []
    for no, sid, name, waterway in STATIONS:
        try:
            info, rows = series(no, "year")
        except Exception as e:
            print(f"{no} {name}: unavailable ({e})"); rows, info = [], None
        days = []
        for r in rows:
            d = r[0][:10]
            v = r[1]
            q = r[2] if len(r) > 2 else None
            cov = r[3] if len(r) > 3 else None
            if v is None or (q is not None and int(q) < 0):
                continue
            days.append((d, v, q, cov))
        by_station[no] = days
        # Possible datum changes: a day-to-day jump bigger than STEP_M between consecutive days with data.
        for (d0, v0, *_), (d1, v1, *_) in zip(days, days[1:]):
            gap = (datetime.fromisoformat(d1) - datetime.fromisoformat(d0)).days
            if abs(v1 - v0) > STEP_M:
                checks.append([no, name, d0, v0, d1, v1, round(v1 - v0, 3), gap])
        s = meta.get(no, {})
        ms = s.get("station_gauge_datum_from")
        stations_rows.append([
            no, sid, name, waterway, s.get("station_latitude", ""), s.get("station_longitude", ""),
            s.get("station_gauge_datum", ""), s.get("station_gauge_datum_unit", ""),
            datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%d") if ms not in (None, "") else "",
            days[0][0] if days else "", days[-1][0] if days else "", len(days),
            sum(1 for c in checks if c[0] == no), (info or {}).get("ts_shortname", ""),
        ])
        print(f"{no} {name}: {len(days)} days" + (f" from {days[0][0]}" if days else ""))
    # Wide table: one row per day, one column per gauge.
    all_days = sorted({d for v in by_station.values() for d, *_ in v})
    look = {no: {d: v for d, v, *_ in days} for no, days in by_station.items()}
    with open(os.path.join(out, "shannon_gauges_daily.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + [sid + "_m" for _, sid, _, _ in STATIONS])
        for d in all_days:
            w.writerow([d] + [look[no].get(d, "") for no, *_ in STATIONS])
    with open(os.path.join(out, "shannon_gauges_daily_long.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "station_no", "station", "level_m", "quality", "quality_meaning", "day_coverage_pct"])
        for no, sid, _, _ in STATIONS:
            for d, v, q, cov in by_station[no]:
                w.writerow([d, no, sid, v, q if q is not None else "", QUALITY.get(q, ""), "" if cov is None else cov])
    with open(os.path.join(out, "stations.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["station_no", "station", "name", "waterway", "latitude", "longitude", "gauge_zero_m",
                    "gauge_zero_datum", "zero_valid_from", "first_day", "last_day", "days_with_data",
                    "possible_datum_steps", "opw_series"])
        w.writerows(stations_rows)
    with open(os.path.join(out, "datum_checks.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["station_no", "name", "day_before", "level_before_m", "day_after", "level_after_m", "change_m", "days_apart"])
        w.writerows(checks)
    print(f"{len(all_days)} days, {len(checks)} possible datum step(s)")


if __name__ == "__main__":
    mode, out = sys.argv[1], sys.argv[2]
    {"log": cmd_log, "daily": cmd_daily}[mode](out)
