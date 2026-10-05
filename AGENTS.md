# Repository guidance

Use the [MIT Coding and Comment Style guide](https://mitcommlab.mit.edu/broad/commkit/coding-and-comment-style/)
and the repository's existing conventions when writing code and documentation.

## Writing

These rules apply to documentation, comments, commit messages, PR
descriptions and dashboard text.

- Lead with what something does and why. Put conditions before instructions.
- Write short, active sentences in the present tense, one idea per sentence.
- Be specific. A sentence the reader can't act on or verify gets cut; for
  example, "Solar stays connected" should say what is connected to what.
- Use lists for steps and rules and tables for comparisons or settings.
  Avoid long paragraphs.
- Give numbers with units and defaults ("100 W", "every 15 minutes").
- Prefer plain words over jargon and abbreviations. Define a term once if the
  reader needs it.
- Avoid filler, hedging, hyperbole and narration about the writing or the
  process ("Note that", "simply", "powerful", "now saves every forecast").
- Cut before adding. When editing, remove stale, redundant or obvious text.

## Code and comments

- Prefer clear names and structure over explanatory comments.
- Comment on rationale, constraints, units, API quirks, and non-obvious
  behavior. Remove comments that repeat the code.
- Keep docstrings to purpose and any inputs, outputs, or limitations the
  signature does not explain.
- Follow existing formatting and line-length settings.

## Documentation

- Keep each README a short summary of its directory: what it is, how to set it
  up and run it, and links to deeper docs. Put detailed reference material,
  such as the charging rules in `docs/charging.md`, in separate files.
- Check claims against the current code, configuration, and workflows. Update
  affected documentation in the same change as the behavior.
- Keep commands runnable from the stated directory, and state required tools.
- Keep generated API documentation synchronized with its source models.

## Dashboard

- Use labels, units, legends and tooltips instead of sentences. Don't explain
  how a metric is calculated or describe what the system is doing in the UI.
- Keep empty states to a few words. Align charts on a shared time axis.
