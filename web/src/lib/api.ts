// Shapes returned by solar-web (server/solar_server/views.py).

export interface Sample {
  t: number;
  battery_pct?: number;
  solar_w?: number;
  ac_input_w?: number;
  output_w?: number;
  moer?: number;
  index?: number;
}

export interface PlugReport {
  t: number;
  on: boolean;
  reason: string;
  w?: number | null;
  index?: number | null;
  plan_at?: number | null;
}

export type Window = [number, number];

export interface Now {
  now: number;
  sample: Sample | null;
  plug: PlugReport | null;
  today: { solar_wh: number; grid_wh: number };
  plan: { generated_at: number; windows: Window[]; index_now?: number } | null;
}

export interface Timeline {
  now: number;
  since: number;
  samples: Sample[];
  plug: PlugReport[];
  forecast: [number, number][];
  windows: Window[];
}

export interface Daily {
  days: { day: string; solar_wh: number; grid_wh: number; battery_peak_pct: number | null }[];
  reserve: { reserve_pct: number | null; good_day_wh?: number; days: number };
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  now: () => get<Now>("/api/now"),
  timeline: (pastHours = 24) => get<Timeline>(`/api/timeline?past_hours=${pastHours}`),
  daily: (days = 14) => get<Daily>(`/api/daily?days=${days}`),
};
