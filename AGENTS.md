# Repository guidance

Use the [MIT Coding and Comment Style guide](https://mitcommlab.mit.edu/broad/commkit/coding-and-comment-style/)
and the repository's existing conventions when writing code and documentation.

## Code and comments

- Prefer clear names and structure over explanatory comments. Use descriptive
  names; explain unfamiliar abbreviations only when needed.
- Comment on rationale, constraints, units, API quirks, and non-obvious behavior.
  Remove comments that merely repeat the code.
- Write comments as concise, complete sentences. Keep docstrings focused on the
  purpose and any inputs, outputs, or limitations the signature does not explain.
- Follow existing formatting and line-length settings. Group related operations
  and wrap prose for readability.

## Documentation

- Check claims against the current implementation, configuration, and workflows.
  Update affected documentation alongside behavior changes.
- Use clear, professional language. Prefer concrete statements and useful examples
  over conversational prose, speculation, or unsupported guarantees.
- Keep instructions runnable from the stated directory. State required tools,
  units, defaults, and fallback behavior where they help the reader act correctly.
- Favor net reductions when reviewing documentation. Remove stale, redundant, or
  obvious text while preserving necessary setup steps, rationale, and limitations.
- Keep generated API documentation synchronized with its source models.
