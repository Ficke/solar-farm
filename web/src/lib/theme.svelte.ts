// index.html sets the initial theme; keep it synchronized afterward.
// Bump version to rebuild canvas charts with the new colors.
export type Mode = "system" | "light" | "dark";

const KEY = "theme";
const media = matchMedia("(prefers-color-scheme: dark)");

function saved(): Mode {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export const theme = $state({ version: 0, mode: saved() });

function apply() {
  const dark = theme.mode === "dark" || (theme.mode === "system" && media.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  theme.version++;
}

export function setMode(mode: Mode) {
  theme.mode = mode;
  try {
    if (mode === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, mode);
  } catch {
    // If storage is blocked, retain the choice until reload.
  }
  apply();
}

media.addEventListener("change", () => theme.mode === "system" && apply());
