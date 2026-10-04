import { align } from "./align";
import type { MixRow } from "./api";

/** CAISO's fuels grouped for the chart, top of the stack first. */
export const GROUPS: { label: string; color: string; keys: (keyof MixRow)[] }[] = [
  { label: "Gas", color: "--mix-gas", keys: ["gas"] },
  { label: "Imports", color: "--mix-imports", keys: ["imports"] },
  { label: "Batteries", color: "--mix-batteries", keys: ["batteries"] },
  { label: "Solar", color: "--solar-area", keys: ["solar"] },
  { label: "Wind", color: "--mix-wind", keys: ["wind"] },
  { label: "Hydro", color: "--mix-hydro", keys: ["large_hydro", "small_hydro"] },
  {
    label: "Other",
    color: "--mix-other",
    keys: ["geothermal", "biomass", "biogas", "coal", "other"],
  },
  { label: "Nuclear", color: "--mix-nuclear", keys: ["nuclear"] },
];

/**
 * Generation by group in GW, as raw values (for the tooltip) and stacked
 * (for drawing, each series the running total from the bottom). Charging
 * batteries and solar's small night-time draw count as zero supply.
 */
export function stackMix(rows: MixRow[]) {
  const gw = (r: MixRow, keys: (keyof MixRow)[]) =>
    Math.max(
      0,
      keys.reduce((sum, k) => sum + ((r[k] as number | null) ?? 0), 0),
    ) / 1000;
  const raw = align(
    GROUPS.map((g) => rows.map((r) => [r.t, gw(r, g.keys)] as [number, number])),
    GROUPS.map(() => 15 * 60),
  );
  const stacked = raw.map((col) => [...col]);
  for (let i = 0; i < raw[0].length; i++) {
    let total = 0;
    for (let k = GROUPS.length; k >= 1; k--) {
      const v = raw[k][i];
      if (v == null) continue;
      total += v;
      stacked[k][i] = total;
    }
  }
  return { raw, stacked };
}
