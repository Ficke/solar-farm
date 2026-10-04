// Share pointer time and source to synchronize charts with the plan strip.
export const hover = $state<{ t: number | null; from: "plan" | "chart" | null }>({
  t: null,
  from: null,
});
