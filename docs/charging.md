# Charging rules

Times are Pacific. Emission rates are WattTime marginal rates in lb CO₂/MWh.

## Plan

The server replans every minute. The plan:

- Fills the battery to 100% by the next 4 pm and keeps it above 20%.
- Charges in the cleanest 15-minute forecast blocks outside 4–9 pm.
- Leaves room for half the expected solar, but only when that is at least
  150 Wh.
- Adds blocks to cover any projected shortfall above 30 Wh against the floor
  or the 4 pm target. If the target can't be met, the plan reports a
  shortfall.

Blocks within 50 lb/MWh of the cleanest remaining block count as a tie. A tie
keeps the block already in the current or next window, so windows move only
for a meaningfully cleaner block. Otherwise the later block wins, leaving room
for solar first.

**Grid to loads.** When the battery is full and no solar room is kept, the
plug also stays on for blocks where running the load from the grid emits less
than running it from the battery and recharging later. A block qualifies when
its rate times the load is at most the rate of the next block the plan would
add, times the battery energy the load would use, divided by 0.9 for charging
losses. With no solar, that allows a rate up to 1/0.81 of the replacement
block. With the plug on, the Jackery passes grid power to its outlets. The plan
reports this energy as `bypass_wh`, included in `grid_wh`.

**Forecast checks.** The current block uses the live rate when it is under 15
minutes old. If a live rate of 300 or more contradicts a forecast of zero, the
day's remaining zero blocks use the recorded rate until a live rate falls
below 100. Blocks without a forecast are skipped. If the forecast can't be
fetched, the server uses its cached copy for up to two hours.

Each plan includes a `blocks` list with one entry per quarter-hour up to 4 pm:
its mode (`charge`, `bypass`, `solar`, `battery`, `peak` or `none`), the
projected charge at its end, and the rate it was compared against. The copy
sent to the plug omits it.

## Estimates

The planner learns from recent telemetry and uses defaults until it has
enough. Gaps over 15 minutes are excluded.

| Estimate | Source | Default |
| --- | --- | --- |
| Solar | Average quarter-hour profile over the last 7 days. A day counts with 6 hours of data between 9 am and 5 pm. Only intervals with the battery below 97% count, since a full battery limits solar input. | 500 Wh/day, 9 am–5 pm |
| Load | Last 24 hours of energy balance: solar and grid in, minus change in charge. Needs 6 hours of data. | 100 W |
| Charge rate | Median of the last 30 plug readings from the past week while charging above 200 W and below 95% battery. Needs 3. | 1,700 W |
| Capacity | Plug-metered Wh per 1% of charge, from charging with no solar. Needs 5% gained in the past week. | 3,072 Wh |
| Solar scale | Panel output per Wh of the Jackery's solar reading, which reads low. Same 5% requirement. | 1.0 |

The Jackery's output reading lags and misses most draws, so load uses it only
when charge readings are missing. The model assumes 90% efficiency for AC
charging and the inverter and 95% for solar charging. Estimates refresh every
30 minutes, or every 5 while net AC input is at least 200 W.

## Plug

The plug script checks these rules in order every minute:

1. **Peak.** Off from 4 to 9 pm, or if the local time is unknown. Exception:
   if a battery reading under 10 minutes old shows 10% or less, the plug turns
   on until the battery reaches 15%.
2. **Current plan.** Follow the plan's windows if it is under 15 minutes old,
   uses battery data and reports no shortfall.
3. **Safety charge.** After 30 hours without grid power, charge for 2 hours.
4. **Older plan.** Follow any plan under 3 hours old.
5. **Live index.** Turn on when WattTime's index (under 15 minutes old) is at
   or below the 25th percentile; stay on until it exceeds 30.
6. **Daytime.** On from 10 am to 3 pm.

While on, the plug stays on across gaps of up to 3 minutes between windows so
replans don't cycle the relay.

## Limitations

- The plan is greedy, so it isn't guaranteed to minimize emissions.
- Learned solar reflects what the panel captured, not the weather forecast.
- Battery readings older than 15 minutes switch the server to a one-hour
  charge (`BUDGET_HOURS`). Without battery data, the plug's fallbacks can't
  size the charge.
- One-minute control can overshoot, especially when charging speed changes.
