# Charging rules

Times are Pacific; emission rates are WattTime marginal rates in lb CO₂/MWh.

## Plan

Every minute the server plans the grid charge needed by the next 4 pm and
puts it in the cleanest 15-minute blocks. The plug follows the current block.

1. **Rates.** One rate timeline: a live rate under 15 minutes old for the
   current block, the forecast after it. A block at 300 or less is clean;
   actual rates sit near 0 or above 800.
2. **Need.** The 4 pm target less the battery now and the solar expected
   before 4 pm. The target is full less a day of expected solar (about 87% in
   October), so the battery has room the next morning. Subtracting today's
   solar leaves room for it.
3. **Rank.** Blocks outside 4-9 pm that end by 3:45 pm, in this order:
   - clean blocks, earliest first;
   - then dirty blocks, cleanest first. Dirty blocks within 100 of the
     cleanest left tie, and the later one wins, since that gap is within
     forecast error.
4. **Fill.** The need goes down the ranking. A gap below the 20% floor fills
   first, from blocks before it.

A forecast zero that turns out dirty needs no special handling. Its block
takes the live rate, ranks as dirty, and its charge moves to the next block.

A target deficit under 100 Wh (about 3%) waits unless the plug is already
charging, so whole-percent readings don't cycle the relay.

The plan projects no load: the battery holds its latest reported level apart
from planned solar and grid charge. Any drain shows up in the next reading
and the next replan.

A full battery in a clean block, with no solar to make room for today or
tomorrow, keeps the plug on so loads run on the clean grid.

A Jackery working mode such as Self-powered stops grid charging and pass-through
above its reserve, so it must stay off; the server alerts when it is on.

## Estimates

Learned from the last 7 days of telemetry, with defaults until there is
enough data:

| Estimate | Default |
| --- | --- |
| Solar profile (only while the battery is below 97%) | 500 Wh/day, 9 am–5 pm |
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
