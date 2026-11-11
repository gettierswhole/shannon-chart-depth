# de Selby’s All Knowing Shannon Almanac

Live Shannon water levels against CSIG chart datum for Lough Derg, Meelick–Athlone and Lough Ree, with lake forecasts, lock and bridge times, marine notices, events on the water and places to eat ashore.

`index.html` is the page; `data.json` holds the live data and is refreshed every two hours.

`datums.json` gives the [OpenCPN plugin](https://github.com/gettierswhole/shannon-depth-opencpn) the same datums, uncertainty bands and caveats as the page. It is made from the REACHES table in `index.html` (so each figure is kept in one place) and the stretch boundaries and lock zones in `tools/boundaries.json`, by the "Make datums.json" workflow whenever either changes.
