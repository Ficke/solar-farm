# Agent guidance

See [README.md](README.md) for what the project does and how to set it up.

## Commands

- `just check` runs lint, format, type checks and tests. Run it before pushing.
- `just test-firestore` runs the Firestore emulator tests (Java 21+).
- After changing `server/solar_server/schema.py`, run `just api`.

## Gotchas

- `device/src/grid-gate.js` must stay ES5 for the Shelly runtime.
- Never probe `/healthz` on Cloud Run; it is reserved. Use `/health`.
- Merging to `main` deploys to production.

## Writing

Applies to docs, comments, commits, PRs and dashboard text.

- Lead with what and why. Use short, specific sentences; cut any the reader
  can't act on or verify.
- No filler, hedging or narration about the work. Give units and defaults.
- Docs should shrink or stay flat. A README is a summary; details go in
  `docs/`. Update docs in the same change as the behavior.
- Dashboard text is labels, units and tooltips, not explanatory sentences.
