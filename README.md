# solar-farm

Grid-aware charging for a Jackery Explorer 3000 v2 with a 250 W solar panel in San Francisco. A Shelly Plug US Gen4 controls AC access, favoring clean grid energy and blocking the PG&E E-TOU-C peak, 4–9 pm Pacific. Solar stays connected.

## How it works

- **Server** (`server/`, `planner/`): reads Jackery telemetry and WattTime's 24-hour marginal-emissions forecast every minute, then replans charging toward a full battery by the next 4 pm.
- **Plug** (`device/src/grid-gate.js`): decides every minute whether to allow grid power. Reports normally return the current plan; separate plan requests recover from missing reports.
- **Dashboard** (`web/`): shows grid state, charging windows, battery and power history, emissions, CAISO generation, forecast accuracy, hub prices, and energy and CO₂ totals.

The plug applies these rules in order:

1. Unknown local time: off. 4–9 pm Pacific: off, unless a battery reading less than 10 minutes old shows **10% or less**. The grid then carries the load until the reading reaches **15%**; in bypass the Jackery feeds its outlets from the grid and charges with the remaining input.
2. A battery-aware plan less than 15 minutes old with no reported shortfall: follow its windows, even if no grid charging is needed.
3. More than 30 hours without grid power: start a two-hour safety charge, subject to rules 1–2.
4. Any plan less than three hours old: follow its windows.
5. A live WattTime index less than 15 minutes old: turn on at or below the 25th percentile; stay on until it exceeds 30.
6. Otherwise: on from 10 am to 3 pm.

While on, the plug bridges gaps of up to three minutes between planned windows to avoid relay cycling during replans.

## Charging policy

The planner targets **100% (3,072 Wh) by the next 4 pm Pacific**, with a **20% floor**. It selects the cleanest available 15-minute forecast blocks outside peak hours. Emissions are grouped by rounding to the nearest **50 lb/MWh**; within a group, later blocks win to allow solar to arrive first.

The current block uses a live marginal rate when it is no more than 15 minutes old. When a live rate of at least **300 lb/MWh** contradicts a zero forecast, the remaining zeros that Pacific day use the recorded rate until a live rate falls below **100 lb/MWh**. Blocks without usable forecast rates are skipped.

Grid charging fills the battery, leaving room for half the estimated later solar only when that allowance reaches **150 Wh**. Additional blocks cover projected floor or deadline deficits above **30 Wh**. Partial windows round up to whole minutes; infeasible plans report a shortfall.

Estimates use recent telemetry:

- **Solar:** the average quarter-hour profile from qualifying days among the last seven completed days. Each needs six hours of coverage between 9 am and 5 pm. The fallback is **500 Wh/day** across those hours.
- **Load:** a time-weighted average over the last 24 hours, requiring six hours of coverage; otherwise **100 W**. Solar and load exclude gaps over 15 minutes.
- **Charging:** the median AC input minus load from the latest 30 qualifying readings in the past week. Each must reach **200 W**; at least three are required, otherwise **1,700 W**.

The energy model assumes 90% input and output efficiency. Estimates are cached for 30 minutes, or five minutes while AC input minus load reaches 200 W. Fresh battery readings adjust the plan every minute. If forecast retrieval fails, the server can replan with a cached forecast for up to two hours.

Battery data older than 15 minutes triggers a labelled **one-hour** fixed-duration fallback. Without battery data, the plug's fallbacks cannot size the charge or guarantee remaining capacity. The greedy plan does not guarantee minimum emissions; learned solar measures captured generation, not weather or curtailed potential. Minute-based control can overshoot, especially when charging speed changes. Jackery's battery protection remains active.

## Setup

1. Create a WattTime account with `CAISO_NORTH` forecast, historical and signal-index access.
2. For optional Jackery telemetry, share the power station with a second account. Jackery permits one login per account, so using the phone app's account can log it out. The integration uses unofficial, read-only [socketry](https://github.com/jlopez/socketry) access; failures trigger fallback planning.
3. Set GitHub Actions secrets `WATTTIME_USERNAME`, `WATTTIME_PASSWORD`, and optionally `JACKERY_EMAIL`, `JACKERY_PASSWORD`, `JACKERY_SN`. The Infra workflow copies credentials into Secret Manager and passes the serial number to Cloud Run.
4. Follow [infra/README.md](infra/README.md) for Google Cloud setup.
5. In the Jackery app, disable schedules and reserve limits that prevent AC charging when the plug is on. Keep charging within the plug's 15 A rating. Verify that switching the plug off preserves load output and solar charging. Setting names depend on firmware; the integration does not change them.
6. Keep the plug in Wi-Fi mode and reserve its IP address in the router.

## Deploy to the plug

Run on the plug's Wi-Fi network:

```sh
cp config/device.example.toml config/device.toml   # set host
gcloud auth login
uv run tools/deploy.py
uv run tools/status.py
```

These uv scripts install dependencies on first run. Deployment reads the plug key and WattTime credentials from Secret Manager; `.env` can override them locally. It sets the timezone, stores settings on the plug, uploads the ES5 script, enables boot startup, and verifies it is running.

The first deploy enables local authentication as `admin` and saves a generated password in git-ignored `config/device.toml`. It protects credentials and relay control on Wi-Fi; cloud control is unaffected. If the password is lost, disable authentication in the Shelly app and redeploy.

Firmware schedules force the relay off at second 59 of the first peak minute and of each half hour after it, and start the script every ten minutes if it has stopped. With the default peak hours, these appear as two “Advanced time” schedules. Custom partial-hour peaks may need more. During the low-battery exception, the script turns the relay on with a three-minute firmware flip-back timer and renews it every minute, so the relay turns off if the script stops. Disable the watchdog schedule before intentionally stopping the script. Each deploy replaces all single-call relay-off schedules for switch 0 and start schedules for grid-gate, including manually created ones; other schedules remain.

## Dashboard and hosting

The [private dashboard](https://solar-web-v5whpbqqpq-uw.a.run.app) requires Google sign-in by an account in `DASHBOARD_USERS`. Hover charts for values; expand them to zoom. Readings refresh every 30 seconds, the timeline every minute, and forecast accuracy and totals every 15 minutes. Hidden tabs pause polling.

One container image serves two Cloud Run services:

- **solar-edge** is public. `/plug/plan` and `/plug/report` require `X-Plug-Key`. Cloud Scheduler calls `/tasks/collect` every minute with a verified Google ID token; it collects readings, fetches the forecast and replans. CAISO mix, hub prices and daily totals update every five minutes; forecasts are archived every 30 minutes. `/tasks/plan` refreshes the plan on demand.
- **solar-web** is behind IAP and serves the dashboard and `/api/now`, `/api/timeline`, `/api/accuracy`, `/api/daily`, and `/api/co2`.

Firestore retains collected readings, mix rows, hub prices and plug reports. Plan history keeps window changes and five-minute snapshots; forecast history keeps half-hour snapshots. Weekly backups are retained for 14 weeks, with seven days of point-in-time recovery.

On relevant pushes to `main`, Deploy runs CI, builds the image and updates both services. A failed rollout or solar-edge `/health` check restores previously recorded serving revisions. OpenTofu manages infrastructure; [infra/README.md](infra/README.md) covers changes. Renovate opens grouped weekly dependency updates; GitHub Actions are pinned to commit SHAs.

## Development

Use [uv](https://docs.astral.sh/uv/) for Python 3.14 and [Bun](https://bun.sh) for JavaScript. [just](https://just.systems) provides optional shortcuts.

```sh
uv sync
uv run pytest
just test-firestore                      # requires Java 21+ and Node
uv run ruff check .
uv run ruff format --check .
uv run ty check
(cd device && bun install && bun test)
(cd web && bun install && bun run check && bun run build)
```

`just check` runs Python lint, format, type and test checks, plug tests, and dashboard checks. CI additionally builds the dashboard and container, tests the Firestore emulator, and validates infrastructure.

For the dashboard with synthetic data, run `uv run uvicorn solar_server.dev:app --port 8000` from `server/` and `bun run dev` from `web/`. It uses Svelte 5, Vite and uPlot. After changing API models in `server/solar_server/schema.py`, run `just api`; dashboard checks and builds regenerate TypeScript types from `web/openapi.json`.

The uv workspace shares root Ruff, ty and pytest settings and `uv.lock`. The plug script must remain ES5; tests enforce this with `ecmaVersion: 5`.

To simulate the next 24 hours without hardware:

```sh
bun device/sim.js            # live windows held fixed and treated as fresh; uses gcloud for the plug key
bun device/sim.js --stale    # ignores the plan and live index; uses the daytime fallback
```

## Tuning

- **Server:** set `SOLAR_DAY_WH`, `LOAD_W`, `CHARGE_W`, or `BATTERY_FLOOR_PCT` environment variables on solar-edge in `infra/run.tf`. Recent measurements replace solar, load and charge-rate defaults.
- **Plug:** override defaults in `[tuning]` in `config/device.toml`, then redeploy.
- **Telemetry fallback:** `BUDGET_HOURS` defaults to one hour and only controls fixed-duration planning without battery data.
