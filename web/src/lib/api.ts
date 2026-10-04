// Shapes returned by solar-web (server/solar_server/views.py).

export interface Sample {
  t: number;
  battery_pct?: number;
  solar_w?: number;
  ac_input_w?: number;
  output_w?: number;
  moer?: number; // WattTime's actual marginal CO2, lb/MWh
  moer_t?: number;
  index?: number; // 0-100 percentile of the past month, lower is cleaner
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
  forecast_health: [number, number][];
  aoer: [number, number][]; // average CO2 across all plants, lb/MWh (hourly, published late)
  health: [number, number][]; // health damage, $/MWh (published a few hours late)
  windows: Window[];
}

export interface Accuracy {
  lead_hours: number;
  points: [number, number, number | null][]; // [t, actual, forecast made lead_hours earlier]
  error: number | null;
  compared: number;
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
  accuracy: (leadHours: number) => get<Accuracy>(`/api/accuracy?lead_hours=${leadHours}`),
};
