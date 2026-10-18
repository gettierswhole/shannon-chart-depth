# Shannon gauge archive

The site's own record of the OPW water-level gauges on the Shannon navigation, from Lough Allen to Portumna and up the Suck to Ballinasloe. It is kept by a GitHub Action (`.github/workflows/archive.yml`, script `tools/archive_gauges.py`) with no AI in the loop.

Levels are in metres above **OD Malin Head (OSGM15)**, exactly as OPW publish them. Waterways Ireland and the lock tables use Poolbeg, which is roughly 2.71 m higher. Nothing here is converted.

## Files

| File | What it holds | Updated |
|---|---|---|
| `shannon_gauges_daily.csv` | One row per day, one column per gauge (`<station>_m`): the daily mean level, from the first day of each gauge's published record. Blank = no data that day. | Sundays |
| `shannon_gauges_daily_long.csv` | The same days in one row per gauge per day, with OPW's quality code and the share of the day the mean is based on. | Sundays |
| `stations.csv` | Each gauge: OPW number, place, waterway, position, gauge zero, the date that zero applies from, first and last day of record. | Sundays |
| `datum_checks.csv` | Every day-to-day change in a daily mean of more than 0.8 m, flagged for a look. Most are floods or gaps, not datum changes. | Sundays |
| `log/YYYY-MM.csv` | Every 15-minute reading, logged as first seen, with the time it was logged. | Daily |

### The log is independent

The daily file is rebuilt from OPW each week, so it follows any corrections OPW make. The log is never rewritten. Each reading is stored the first time the script sees it, with the time it was logged. A boater's timestamped reading can therefore always be checked against what the gauge said then, even if OPW later revise, withdraw or stop publishing that value. Where the two disagree, the log is what was published on the day and the daily file is OPW's current view.

## Quality codes (OPW)

| Code | Meaning for water level |
|---|---|
| 31 | Inspected |
| 32 | Corrected |
| 101 | Unreliable, suspected to be wrong |
| 254 | Unchecked, provisional (normal for recent readings) |

Others (41, 42, 99, 102, 151, 225) appear on a few hundred days. They are kept as published; OPW's hydrometric section (hydrometric@opw.ie) can say what they mean.

## How far back

Each gauge goes back to the start of the record that OPW publish online, given in `stations.csv` as `first_day`. Shannonbridge starts in 1983, Banagher in 1989, Boyle in 1990, Lough Allen in 1994. Several gauges are older than their online record: Athlone has a gauge zero from 1952 but data from 2007, Jamestown 1976/2005, Drumsna 1984/2007 and Meelick 1985/2003. OPW may hold the older years on request.

## Checked so far (October 2026)

- **No Poolbeg/Malin mix-ups found.** All series move together through the wet years (2008, 2019–20, 2023). The year-by-year median difference between neighbouring gauges stays steady: Hodson's Bay to Derry Bay within 2 to 4 cm, Drumsna to Carrick within 1.84 to 1.96 m, Meelick to Banagher within 1.0 to 1.24 m. A datum change would show as a lasting step in one of these, and there is none.
- **Derry Bay, Nov 2005 to Feb 2006: suspect.** For a few weeks it reads up to about 55 cm above Athlone Weir U/S and Hodson's Bay, then drops by about 1 m overnight, several times. A lake can't do that. Leave those days out of any analysis.
- **Lough Derg** has no OPW gauge on the lake itself. Portumna Bridge (from May 2023) is the nearest; the Killaloe gauges belong to ESB.

Source: OPW Hydro-Data, [waterlevel.ie/hydro-data](https://waterlevel.ie/hydro-data/), licensed CC BY 4.0. Contains Office of Public Works data.
