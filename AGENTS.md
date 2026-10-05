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

- Lead with what and why. Use short, active, specific sentences; cut any the
  reader can't act on or verify.
- Use lists and tables over paragraphs. Give units and defaults.
- No filler, hedging, hype or narration about the work.
- Check every claim against the code. Update docs with the behavior they
  describe.
- Cut text rather than moving it elsewhere.
- A README summarizes its directory (what, setup, use) and links to details.
- AGENTS.md holds only what an agent can't infer: commands, gotchas and
  rules. No README content or generic advice.
- Dashboard text is labels, units and tooltips, not explanatory sentences.
