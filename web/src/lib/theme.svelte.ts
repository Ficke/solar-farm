// Bumped when the system switches between light and dark. Canvas charts read
// their colors when built, so they rebuild on a change.
export const theme = $state({ version: 0 });

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => theme.version++);
