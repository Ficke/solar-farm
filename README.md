# solar-farm

Grid-aware charging for a Jackery Explorer 3000 v2 with a 250 W panel in a San Francisco apartment. A Shelly Plug US Gen4 sits between the wall and the Jackery and only lets grid power through when California's grid is clean, and never during the PG&E E-TOU-C peak (4pm to 9pm).

## How it works

- **Jackery:** Self-powered mode with the outage reserve at about 80%. The grid only charges the battery up to the reserve; the space above it is left for the panel. When the plug cuts power, the Jackery treats it as an outage and runs everything from the battery.
- **Shelly plug** (`device/src/grid-gate.js`): a script on the plug decides every minute whether the grid is on, in this order:
  1. 4pm to 9pm Pacific: always off.
  2. Grid off for 18 hours: on for 2 hours, so the battery can't run flat.
  3. A plan less than 3 hours old: on inside its windows.
  4. Otherwise WattTime's live index for `CAISO_NORTH`: on at or below the 25th percentile.
  5. No internet: on from 10am to 3pm.
- **Planner** (`planner/`, run by `.github/workflows/plan.yml` every 30 minutes): reads WattTime's 24-hour marginal-emissions forecast, picks the cleanest 4 hours outside the peak, and publishes `plan.json` to GitHub Pages. It also records a Jackery telemetry sample (battery %, solar watts) from Jackery's cloud.
- **Reserve recommendation** (`.github/workflows/recommend.yml`, weekly): turns two weeks of solar telemetry into a suggested reserve and posts it on the "Reserve recommendation" issue. The reserve itself is set by hand in the Jackery app.

## One-time setup

1. **WattTime:** create a free account at [watttime.org](https://watttime.org). The free plan includes full `CAISO_NORTH` data.
2. **Jackery cloud (optional, for telemetry):** create a second Jackery account and share the power station to it from the app. Jackery allows one login at a time, so the planner must not use the account on your phone. The access is unofficial (via [socketry](https://github.com/jlopez/socketry)) and read-only; if it breaks, the plan keeps working.
3. **Repository secrets** (Settings > Secrets and variables > Actions): `WATTTIME_USERNAME`, `WATTTIME_PASSWORD`, and optionally `JACKERY_EMAIL`, `JACKERY_PASSWORD`, `JACKERY_SN`.
4. **GitHub Pages:** run the Plan workflow once (Actions > Plan > Run workflow), then Settings > Pages > Deploy from branch `gh-pages`, folder `/`.
5. **Jackery app:** Self-powered on, reserve 80%, Quiet Charging on (keeps the charge rate well under the plug's 15 A rating).
6. **Plug:** keep it in Wi-Fi mode and note its IP address.

## Deploying to the plug

From a computer on your home Wi-Fi:

```sh
pip install -r tools/requirements.txt
cp config/device.example.toml config/device.toml   # set host
cp .env.example .env                                # WattTime login for the live-index fallback
python tools/deploy.py
python tools/status.py
```

`deploy.py` sets the plug's timezone, writes settings into the plug's key-value store (secrets never go in the repo), uploads the script in 1 KB chunks, enables it on boot and starts it.

## Development

```sh
cd device && npm install && npm test        # script logic under a fake Shelly runtime
cd planner && pip install -e '.[dev]' && pytest
```

The script must stay ES5: the test suite parses it with `ecmaVersion: 5`.

## Tuning

- **Reserve:** follow the weekly recommendation. Rule of thumb: if the battery hits 100% on sunny afternoons, lower it; if it never gets close, raise it.
- **Script settings:** `[tuning]` in `config/device.toml` overrides the script defaults (threshold, peak hours, fallback window); rerun `deploy.py`.
- **Daily grid window:** `--budget-hours` in `plan.yml`.

Note: `gh-pages` is public, including `data/telemetry.csv` (battery and solar readings).
