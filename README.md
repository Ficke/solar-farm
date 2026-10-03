# solar-farm

Grid-aware charging for a Jackery Explorer 3000 v2 with a 250 W panel in a San Francisco apartment. A Shelly Plug US Gen4 sits between the wall and the Jackery and only lets grid power through when California's grid is clean, and never during the PG&E E-TOU-C peak (4pm to 9pm).

## How it works

- **Jackery:** Self-powered mode with the outage reserve at about 80%. The grid only charges the battery up to the reserve; the space above it is left for the panel. When the plug cuts power, the Jackery treats it as an outage and runs everything from the battery.
- **Shelly plug** (`device/src/grid-gate.js`): a script on the plug decides every minute whether the grid is on, in this order:
  1. 4pm to 9pm Pacific: always off.
  2. Grid off for 30 hours (a whole missed day): on for 2 hours, so the battery can't run flat.
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
cp config/device.example.toml config/device.toml   # set host
cp .env.example .env                                # WattTime login for the live-index fallback
uv run tools/deploy.py
uv run tools/status.py
```

Both tools are [uv scripts](https://docs.astral.sh/uv/guides/scripts/): uv installs their dependencies on first run.

`deploy.py` sets the plug's timezone, writes settings into the plug's key-value store (secrets never go in the repo), uploads the script in 1 KB chunks, enables it on boot and starts it.

## Dashboard

GitHub Pages serves a small status page at https://ficke.github.io/solar-farm/ with the upcoming grid windows and the last week of battery and solar readings.

## Dry run without the plug

```sh
bun device/sim.js            # what the plug would do over the next 24 h with the live plan
bun device/sim.js --stale    # same, if the plan stopped updating (fallback rules)
```

## Google Cloud (in progress)

A private live dashboard is being built on Google Cloud Run, and it will eventually replace the GitHub Pages files. All of it is defined in OpenTofu under [`infra/`](infra/README.md), which also has the one-time setup steps.

## Development

Tools: [uv](https://docs.astral.sh/uv/) for Python (it installs Python 3.14 itself), [Bun](https://bun.sh) for the plug script's tests, and optionally [just](https://just.systems) for the shortcuts in `justfile`.

```sh
uv sync                                  # Python 3.14 + all dependencies into .venv
uv run pytest                            # planner tests
uv run ruff check . && uv run ty check   # lint and type check
cd device && bun install && bun test     # script logic under a fake Shelly runtime
```

Or `just check` to run everything CI runs. The repo is a uv workspace: the root `pyproject.toml` holds the shared Ruff, ty and pytest settings and one `uv.lock`; `planner/` is a member package.

The script must stay ES5: the test suite parses it with `ecmaVersion: 5`.

## Tuning

- **Reserve:** follow the weekly recommendation. Rule of thumb: if the battery hits 100% on sunny afternoons, lower it; if it never gets close, raise it.
- **Script settings:** `[tuning]` in `config/device.toml` overrides the script defaults (threshold, peak hours, fallback window); rerun `deploy.py`.
- **Daily grid window:** `--budget-hours` in `plan.yml`.

Note: `gh-pages` is public, including `data/telemetry.csv` (battery and solar readings).
