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
- **Server** (`server/` and `planner/`, on Google Cloud Run): every 30 minutes it reads WattTime's 24-hour marginal-emissions forecast and picks the cleanest 4 hours outside the peak, which the plug reads from `/plug/plan`. Every 5 minutes it records the battery %, solar watts (from Jackery's cloud), grid emissions and CAISO's generation by source, and the plug reports its state every minute.
- **Dashboard** (`web/`): the private page described below. It also suggests a reserve from two weeks of solar readings; the reserve itself is set by hand in the Jackery app.

## One-time setup

1. **WattTime:** create a free account at [watttime.org](https://watttime.org). The free plan includes full `CAISO_NORTH` data.
2. **Jackery cloud (optional, for telemetry):** create a second Jackery account and share the power station to it from the app. Jackery allows one login at a time, so the planner must not use the account on your phone. The access is unofficial (via [socketry](https://github.com/jlopez/socketry)) and read-only; if it breaks, the plan keeps working.
3. **Repository secrets** (Settings > Secrets and variables > Actions): `WATTTIME_USERNAME`, `WATTTIME_PASSWORD`, and optionally `JACKERY_EMAIL`, `JACKERY_PASSWORD`, `JACKERY_SN`. The Infra workflow copies them into Google Secret Manager.
4. **Google Cloud:** follow [`infra/README.md`](infra/README.md).
5. **Jackery app:** Self-powered on, reserve 80%, Quiet Charging on (keeps the charge rate well under the plug's 15 A rating).
6. **Plug:** keep it in Wi-Fi mode, reserve its IP address in the router's DHCP settings and note that address.

## Deploying to the plug

From a computer on your home Wi-Fi:

```sh
cp config/device.example.toml config/device.toml   # set host
gcloud auth login                                   # deploy.py reads secrets from Secret Manager
uv run tools/deploy.py
uv run tools/status.py
```

Both tools are [uv scripts](https://docs.astral.sh/uv/guides/scripts/): uv installs their dependencies on first run.

`deploy.py` sets the plug's timezone, writes settings into the plug's key-value store (secrets never go in the repo), uploads the script in 1 KB chunks, enables it on boot and starts it. It reads the plug key and WattTime credentials from Google Secret Manager, where the Infra workflow copied the repository secrets. A local `.env` is only needed to override those values during development.

It also protects the plug:

- **Local password.** On the first run it turns on the plug's password (user `admin`) and saves it as `password` in `config/device.toml`, which is git-ignored. Without one, anyone on the Wi-Fi could read the plug key and WattTime login from the plug. The Shelly app asks for it when you open the plug on your home network; cloud control is unaffected. If you lose it, turn off authentication in the Shelly app and deploy again.
- **Firmware backstops** that work even if the script stops: a schedule switches the relay off every minute from 4:01pm to 8:59pm (the script itself switches off at 4:00pm), and another restarts the script every 10 minutes. Both follow `peakStart`/`peakEnd` in `[tuning]`. To pause the script on purpose, disable that schedule in the Shelly app first. Deploy replaces only the schedules it made.

## Dashboard

The private dashboard is at https://solar-web-v5whpbqqpq-uw.a.run.app (Google sign-in; only the accounts in the `DASHBOARD_USERS` variable get in). It leads with whether the grid is on, why, and when it next changes, then the plan in one place (a 24-hour strip and a list of windows), WattTime's actual and forecast emissions, CAISO's generation by source, a check of how far off the forecast was 1 to 12 hours ahead, the battery and power history, the last week's energy, and the suggested reserve. Hover a chart for exact times and values. It refreshes itself every 30 seconds.

Every reading, grid mix row, plug report, plan and forecast is kept in Firestore, with a weekly backup kept for 14 weeks.

## Dry run without the plug

```sh
bun device/sim.js            # what the plug would do over the next 24 h with the live plan (uses your gcloud login for the plug key)
bun device/sim.js --stale    # same, if the plan stopped updating (fallback rules)
```

## Google Cloud

The dashboard and the plug's server run on Google Cloud Run. All of it is defined in OpenTofu under [`infra/`](infra/README.md), which also has the one-time setup steps. The server in `server/` runs as two Cloud Run services from one image:

- **solar-edge** (public) serves the plug, which reads `/plug/plan` and posts `/plug/report` each minute with its `X-Plug-Key`. It also serves Cloud Scheduler: `/tasks/collect` every 5 minutes records Jackery, WattTime and CAISO readings in Firestore, and `/tasks/plan` every 30 minutes builds the plan.
- **solar-web** (behind Google sign-in) serves the dashboard from `web/` and its API: `/api/now`, `/api/timeline`, `/api/accuracy` and `/api/daily`.

The Deploy workflow runs CI, builds the image and rolls it out on every merge to `main`. If solar-edge's `/health` doesn't answer afterwards, both services go back to the revisions they were serving before. [Renovate](https://docs.renovatebot.com) opens one grouped update PR a week (`renovate.json`), with GitHub Actions pinned to commit SHAs.

## Development

Tools: [uv](https://docs.astral.sh/uv/) for Python (it installs Python 3.14 itself), [Bun](https://bun.sh) for the plug script's tests, and optionally [just](https://just.systems) for the shortcuts in `justfile`.

```sh
uv sync                                  # Python 3.14 + all dependencies into .venv
uv run pytest                            # planner and server tests
just test-firestore                      # server store against the Firestore emulator (Java 21+)
uv run ruff check . && uv run ty check   # lint and type check
cd device && bun install && bun test     # script logic under a fake Shelly runtime
cd web && bun install && bun run check   # dashboard type check and lint
```

To work on the dashboard with made-up readings, run `uv run uvicorn solar_server.dev:app --port 8000` from `server/` and `bun run dev` in `web/`. The dashboard is Svelte 5 with Vite and uPlot. Its API types come from the server: after changing `server/solar_server/schema.py`, run `just api` to update `web/openapi.json`, and the dashboard's check and build regenerate the TypeScript types from it.

Or `just check` to run everything CI runs. The repo is a uv workspace: the root `pyproject.toml` holds the shared Ruff, ty and pytest settings and one `uv.lock`; `planner/` and `server/` are member packages.

The script must stay ES5: the test suite parses it with `ecmaVersion: 5`.

## Tuning

- **Reserve:** follow the dashboard's suggestion. Rule of thumb: if the battery hits 100% on sunny afternoons, lower it; if it never gets close, raise it.
- **Script settings:** `[tuning]` in `config/device.toml` overrides the script defaults (threshold, peak hours, fallback window); rerun `deploy.py`.
- **Daily grid window:** add `BUDGET_HOURS` (default 4) to solar-edge's environment in `infra/run.tf`.
