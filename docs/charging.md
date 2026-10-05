# Charging rules

Times are Pacific; emission rates are WattTime marginal rates in lb CO₂/MWh.

## Plan

The server replans every minute to fill the battery by 4 pm, keeping it
above 20%. It charges in the cleanest 15-minute forecast blocks outside
4–9 pm and leaves room for half the expected solar when that is at least
150 Wh. Blocks within 50 lb/MWh of the cleanest count as a tie; the block
already planned wins, otherwise the later one.

Once the battery is full, the plug also stays on, passing grid power to the
loads, in blocks cleaner than running the loads from the battery and
recharging later (about 1/0.81 of the replacement block's rate, at 90%
efficiency each way).

A live rate under 15 minutes old replaces the forecast for the current block.
If a live rate of 300 or more contradicts a zero forecast, the day's remaining
zeros use the live rate until it falls below 100.

## Estimates

Learned from the last 7 days of telemetry, with defaults until there is
enough data:

| Estimate | Default |
| --- | --- |
| Solar profile (only while the battery is below 97%) | 500 Wh/day, 9 am–5 pm |
| Load, from energy balance over 24 hours | 100 W |
| Charge rate, from the plug meter | 1,700 W |
| Capacity, from plug-metered charging | 3,072 Wh |

## Plug

The plug script applies the first matching rule every minute:

1. **Peak:** off 4–9 pm, unless the battery is at 10% or less; then on until
   15%.
2. **Plan:** follow a plan under 15 minutes old with no shortfall.
3. **Safety:** after 30 hours without grid power, charge for 2 hours.
4. **Older plan:** follow any plan under 3 hours old.
5. **Live index:** on at or below WattTime's 25th percentile, off above 30.
6. **Daytime:** on 10 am–3 pm.
