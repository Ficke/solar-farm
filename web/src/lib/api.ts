// Shapes returned by solar-web, generated from openapi.json (server/solar_server/schema.py).
import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type Sample = Schemas["Sample"];
export type PlugReport = Schemas["StoredPlugReport"];
export type MixRow = Schemas["MixRow"];
export type Window = Schemas["Window"];
export type Now = Schemas["Now"];
export type Timeline = Schemas["Timeline"];
export type Accuracy = Schemas["Accuracy"];
export type Daily = Schemas["Daily"];
export type Co2 = Schemas["Co2"];
export type Period = Co2["by"];

type Path = keyof paths;
type Query<P extends Path> = paths[P]["get"]["parameters"]["query"];
type Response<P extends Path> = paths[P]["get"]["responses"][200]["content"]["application/json"];

async function get<P extends Path>(path: P, query?: Query<P>): Promise<Response<P>> {
  const qs = query ? `?${new URLSearchParams(query as Record<string, string>)}` : "";
  const r = await fetch(path + qs, { headers: { accept: "application/json" } });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return (await r.json()) as Response<P>;
}

export const api = {
  now: () => get("/api/now"),
  timeline: (pastHours = 24) => get("/api/timeline", { past_hours: pastHours }),
  daily: (days = 14) => get("/api/daily", { days }),
  accuracy: (leadHours: number) => get("/api/accuracy", { lead_hours: leadHours }),
  co2: (by: Period, count: number) => get("/api/co2", { by, count }),
};
