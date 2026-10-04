# solar-farm

Grid-aware charging for a Jackery Explorer 3000 v2 with a 250 W panel in a San Francisco apartment. A Shelly Plug US Gen4 sits between the wall and the Jackery and only lets grid power through when California's grid is clean, and never during the PG&E E-TOU-C peak (4pm to 9pm).

## How it works

- **Jackery:** no mode schedule or reserve slider is used to control charging. The server decides how much grid energy is needed and the Shelly controls AC access. Solar stays connected. The Jackery must accept AC charging while the plug is on and keep powering the load when it is off; select settings that allow that in the app. The scheduler measures the AC charge rate from telemetry, starting from 1,700 W.
- **Shelly plug** (`device/src/grid-gate.js`): a script on the plug decides every minute whether the grid is on, in this order:
  1. 4pm to 9pm Pacific: always off.
  2. A feasible battery-aware plan less than 15 minutes old: follow its windows, including no grid at all when solar covers demand.
  3. Otherwise, grid off for 30 hours (a whole missed day): on for 2 hours, so the battery can't run flat. Then follow any plan less than 3 hours old.
  4. Otherwise WattTime's live index for `CAISO_NORTH`: on at or below the 25th percentile.
  5. No internet: on from 10am to 3pm.
- **Server** (`server/` and `planner/`, on Google Cloud Run): every minute it reads WattTime's 24-hour marginal-emissions forecast, which WattTime updates every 5 minutes. With fresh battery telemetry, it plans enough grid time in the cleanest 15-minute blocks before 4 pm to leave the battery full, shortening the final block to whole minutes. It reads the Jackery every minute and replans after each reading; if the forecast can't be fetched, it replans with the last one for up to two hours. The plug reads `/plug/plan` and reports its state every minute.
- **Dashboard** (`web/`): shows windows, planned grid Wh, the solar estimate, and any projected shortfall from full. It labels the fixed-duration fallback when battery telemetry is unavailable.

## Charging policy

The goal each day is a **full battery by 4 pm**, when the peak starts, with the grid energy bought when the grid is cleanest and solar used where it matters.

1. **Deadline and target:** the next 4 pm Pacific; full (3,072 Wh).
2. **Cleanest first:** forecast 15-minute blocks before 4 pm, outside 4–9 pm, are ranked by marginal CO₂. Blocks within **50 lb/MWh** of each other count as equally clean and the later one wins, so solar gets in first.
3. **Fill to full:** grid tops the battery up to full in those blocks, cleanest first, stopping at the first block that reaches full. Solar before a block is already counted in the projected level.
4. **Room for solar, only when it matters:** a block leaves room for solar still expected after it, counted at half the usual output, and only when that is at least **150 Wh** (about 5%). A little afternoon solar is not worth missing a clean window for.
5. **Backstops:** projected charge never drops below **20%**, and if load or a short window leaves the battery more than 30 Wh short at 4 pm, the next cleanest block covers it. A shortfall is reported if that is impossible.

Solar starts at **500 Wh/day** spread over 9am–5pm and is learned as an average time-of-day profile from the last seven completed days with at least six hours of telemetry between 9am and 5pm; gaps over 15 minutes are excluded.

Load is the time-weighted average of the last 24 hours, with a 100 W fallback until there are six hours of valid readings. The charge rate is the median grid power into the battery (AC in less load) over the last week's readings of at least 200 W, once there are three; until then it is the configured **1,700 W**. The energy model assumes 90% efficiency for input and output. Solar/load summaries are cached for 30 minutes, so the one-minute replans normally read just the latest battery state and the cached estimates. Forecast blocks are ranked once per plan. No additional controller or optimization service is needed.

Fresh state of charge corrects the plan every minute: more solar than expected shortens the windows; less solar or unexpected drain lengthens them or brings charging forward. A failed replan is logged without discarding a successful telemetry collection. Neither the one-minute telemetry loop nor the plug's one-minute relay loop is an exact hardware charge limit: allow for overshoot, especially if charging speed changes. This is a greedy scheduler, not a guarantee of globally minimum emissions. Learned solar is captured generation, not a weather forecast or a measurement of curtailed potential.

Battery readings older than 15 minutes trigger a labelled **one-hour** clean-grid fallback. Cached emissions forecasts are only reused for two hours. Internet and telemetry failures retain the plug's live-index, daytime and emergency fallbacks; without battery data they cannot size the charge. Jackery's own battery protection remains active.

## One-time setup

1. **WattTime:** create a free account at [watttime.org](https://watttime.org). The free plan includes full `CAISO_NORTH` data.
2. **Jackery cloud (optional, for telemetry):** create a second Jackery account and share the power station to it from the app. Jackery allows one login at a time, so the planner must not use the account on your phone. The access is unofficial (via [socketry](https://github.com/jlopez/socketry)) and read-only; if it breaks, the plan keeps working.
3. **Repository secrets** (Settings > Secrets and variables > Actions): `WATTTIME_USERNAME`, `WATTTIME_PASSWORD`, and optionally `JACKERY_EMAIL`, `JACKERY_PASSWORD`, `JACKERY_SN`. The Infra workflow copies them into Google Secret Manager.
4. **Google Cloud:** follow [`infra/README.md`](infra/README.md).
5. **Jackery app:** disable its charging schedule and reserve-based charging limit so AC charging follows the plug. Keep the charging speed within the plug's 15 A rating. Verify that turning the plug off preserves load output and solar charging; exact setting names depend on firmware. The integration is read-only and does not change app settings.
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

The private dashboard is at https://solar-web-v5whpbqqpq-uw.a.run.app (Google sign-in; only the accounts in the `DASHBOARD_USERS` variable get in). It leads with whether the grid is on, why, and when it next changes, then the plan in one place (a 24-hour strip and a list of windows), WattTime's actual and forecast emissions, CAISO's generation by source, a check of how far off the forecast was 1 to 12 hours ahead, the battery and power history (solar and grid in, load out), CO₂ avoided by day, week or month, and the last week's energy. Hover a chart for exact times and values. It refreshes itself every 30 seconds.

Every reading, grid mix row, plug report, plan and forecast is kept in Firestore, with a weekly backup kept for 14 weeks.

## Dry run without the plug

```sh
bun device/sim.js            # what the plug would do over the next 24 h with the live plan (uses your gcloud login for the plug key)
bun device/sim.js --stale    # same, if the plan stopped updating (fallback rules)
```

## Google Cloud

The dashboard and the plug's server run on Google Cloud Run. All of it is defined in OpenTofu under [`infra/`](infra/README.md), which also has the one-time setup steps. The server in `server/` runs as two Cloud Run services from one image:

- **solar-edge** (public) serves the plug, which reads `/plug/plan` and posts `/plug/report` each minute with its `X-Plug-Key`. It also serves Cloud Scheduler: `/tasks/collect` every minute records the Jackery and any new WattTime reading in Firestore, fetches the forecast and updates the plan. Every 5 minutes it records CAISO's mix; every 30 minutes it keeps a copy of the forecast. `/tasks/plan` refreshes the forecast and plan on demand.
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

- **Solar and battery:** the planner learns the solar profile automatically. Initial server settings are `SOLAR_DAY_WH=500`, `LOAD_W=100`, `CHARGE_W=1700`, and `BATTERY_FLOOR_PCT=20`. Override these on solar-edge in `infra/run.tf` if needed. Solar, load and charging fallbacks yield to recent measurements.
- **Script settings:** `[tuning]` in `config/device.toml` overrides the script defaults (threshold, peak hours, fallback window); rerun `deploy.py`.
- **Telemetry fallback:** `BUDGET_HOURS` (default 1) controls fixed-duration charging only when battery telemetry is unavailable; it is not the adaptive plan's daily quota.
