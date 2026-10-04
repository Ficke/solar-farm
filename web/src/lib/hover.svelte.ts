// The time under the pointer, shared so the plan strip and every chart scrub
// together. `from` says which kind of view the pointer is over.
export const hover = $state<{ t: number | null; from: "plan" | "chart" | null }>({
  t: null,
  from: null,
});
