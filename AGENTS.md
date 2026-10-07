# Agent instructions

- Follow the [development conventions](README.md#development) and
  [test guide](tests/README.md).
- Consult the [architecture](docs/architecture/Overview.md) and relevant
  [design documents](docs/architecture/) when changing system behavior.
- Never assume migration support or backward compatibility is required, or make
  design or implementation decisions to preserve either, unless the user
  explicitly requests it.
- Add short, clear comments at the relevant code location only to explain
  motivation, reasons, or logic that are not obvious from the code. A bug fix alone
  does not justify a comment; a useful comment explains the non-obvious reason
  behind the fix to help LLMs avoid repeating the mistake.
- Run affected tests after edits; finish with related regressions and
  `uv run pytest -q`. Run integration/native suites when their boundaries change.
- After structural Program changes, run
  `uv run python -m evertree.core.programs.layout`.
