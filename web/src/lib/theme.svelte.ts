// Light, dark or follow the system. index.html applies the saved choice
// before first paint; this keeps it in sync afterwards. Canvas charts read
// their colors when built, so `version` bumps make them rebuild.
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
    // Storage blocked: the choice lasts until reload.
  }
  apply();
}

media.addEventListener("change", () => theme.mode === "system" && apply());
