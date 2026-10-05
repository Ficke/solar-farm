# solar-farm

Charges a home battery from the grid when the grid is cleanest, and never
during PG&E's 4–9 pm peak.

The battery is a Jackery Explorer 3000 v2 with a 250 W solar panel. A Shelly
Plug US Gen4 switches the Jackery's AC input on and off; the panel charges it
regardless of the plug. A server uses WattTime's marginal-emissions forecast
for Northern California (`CAISO_NORTH`) to schedule grid charging so the
battery is full by 4 pm each day.

## How it works

| Part | Location | Role |
| --- | --- | --- |
| Planner | `planner/` | Picks the cleanest 15-minute blocks to charge, from the forecast and recent battery, solar and load data. |
| Server | `server/` | Every minute, reads the Jackery, fetches the forecast, and replans. Serves the plan to the plug and data to the dashboard. |
| Plug script | `device/` | Switches the relay every minute according to the plan, with fallbacks if the server is unreachable. |
| Dashboard | `web/` | Battery, plan, emissions, grid mix and CO₂ history. [Private](https://solar-web-v5whpbqqpq-uw.a.run.app); Google sign-in. |
| Infrastructure | `infra/` | Google Cloud (Cloud Run, Firestore, Cloud Scheduler) managed with OpenTofu. |

[docs/charging.md](docs/charging.md) describes the planning rules and the
plug's fallbacks.

## Setup

1. Create a [WattTime](https://watttime.org) account with `CAISO_NORTH` access.
2. Optional: share the Jackery with a second Jackery account for telemetry.
   Jackery allows one login per account, so the phone app's account would be
   signed out. Telemetry uses the unofficial
   [socketry](https://github.com/jlopez/socketry) library. Without battery
   data, the server plans one hour of charging in the cleanest blocks.
3. Set GitHub Actions secrets `WATTTIME_USERNAME` and `WATTTIME_PASSWORD`, and
   optionally `JACKERY_EMAIL`, `JACKERY_PASSWORD` and `JACKERY_SN`.
4. Set up Google Cloud with [infra/README.md](infra/README.md).
5. In the Jackery app, turn off schedules and reserve limits that block AC
   charging. Confirm that loads and solar charging continue with the plug off.
6. Reserve the plug's IP address in your router, then
   [deploy the plug script](device/README.md).

Merging to `main` runs CI and deploys the server and infrastructure.

## Development

Requires [uv](https://docs.astral.sh/uv/), [Bun](https://bun.sh) and
[just](https://just.systems).

```sh
just setup            # install dependencies
just check            # lint, type-check and test Python, plug and dashboard
just test-firestore   # Firestore emulator tests; requires Java 21+ and Node
just web              # dashboard at http://localhost:5173 with synthetic data
```

After changing API models in `server/solar_server/schema.py`, run `just api`
to regenerate the dashboard's types.

## Configuration

- **Server:** `SOLAR_DAY_WH` (default 500), `LOAD_W` (100), `CHARGE_W` (1700)
  and `BATTERY_FLOOR_PCT` (20) on solar-edge in `infra/run.tf`. Measured
  values replace the first three once enough telemetry exists.
- **Plug:** `[tuning]` in `config/device.toml`, then redeploy.

## License

[MIT](LICENSE)
