import { align } from "./align";
import type { MixRow } from "./api";

/** Order fuel groups from the top of the chart stack. */
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

/** Average within 15 minutes on each side of a point. */
const SMOOTH = 15 * 60;

/**
 * Return raw group values and a smoothed cumulative stack, in GW.
 * Average the stack over a centered 30-minute span; keep tooltip values raw.
 * Clamp negative supply, including charging batteries, to zero.
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
  const xs = raw[0] as number[];
  const smooth = raw.map((col, k) =>
    k === 0
      ? col
      : col.map((v, i) => {
          if (v == null) return v;
          let sum = 0;
          let n = 0;
          for (let j = i; j >= 0 && xs[i] - xs[j] <= SMOOTH; j--) {
            const w = col[j];
            if (w != null) {
              sum += w;
              n++;
            }
          }
          for (let j = i + 1; j < xs.length && xs[j] - xs[i] <= SMOOTH; j++) {
            const w = col[j];
            if (w != null) {
              sum += w;
              n++;
            }
          }
          return sum / n;
        }),
  );
  const stacked = smooth.map((col) => [...col]);
  for (let i = 0; i < raw[0].length; i++) {
    let total = 0;
    for (let k = GROUPS.length; k >= 1; k--) {
      const v = smooth[k][i];
      if (v == null) continue;
      total += v;
      stacked[k][i] = total;
    }
  }
  return { raw, stacked };
}
