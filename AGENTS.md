# Documentation

- [Architecture overview](docs/architecture/Overview.md)
- [Architecture documents](docs/architecture/)

# Engineering Principles

- Keep `__init__.py` files limited to package docstrings. Define components in
  named modules and import them from their defining modules; do not add package
  re-exports or compatibility aliases.
- Keep interfaces and data models minimal and elegant: every field, parameter, and option must have a current purpose.
- Add short, clear comments at the relevant code location only to explain
  motivation, reasons, or logic that are not obvious from the code. A bug fix alone
  does not justify a comment; a useful comment explains the non-obvious reason
  behind the fix to help LLMs avoid repeating the mistake.
- Keep trusted execution, isolation, and mandatory acceptance checks in `core`;
  evolving behavior belongs in `processes`, reusable Program helpers in `common`.
- Call other Programs through the runtime, including other roles of the same
  process; do not import their implementations directly.
- Keep `processes/` aligned with the Self/Process `SUBTYPE_OF` taxonomy;
  `PART_WHOLE` does not define directory nesting. Preserve stable IDs when
  updating graph names, paths, and references. Validate structural changes with
  `uv run python -m evertree.core.programs.layout`.

# Testing

- Prefer the smallest real set of components that proves the behavior. Use Git,
  subprocesses, DBOS, application startup, or native sandboxes only when their
  behavior is part of the test.
- Default to `tests/unit` or `tests/component`, including complex behavioral
  scenarios. Create task/store objects directly when intake is not under test.
- Run unit, component, and portable integration tests in parallel by default;
  pytest already selects up to four workers. Use `-n 0` for a single test,
  sequential debugging, and native/live suites.
- After a local edit, run the affected tests. After completing the change, run
  related regressions and the fast default suite (`uv run pytest -q`). Run the
  integration/native suites when their boundaries change; do not rerun every
  suite after each edit. Use `-n 0` for one test or sequential debugging.
- A complex or expensive test must state its contract and justify its real
  infrastructure in a short docstring. Never mock the behavior being asserted.
- Keep mutable state private to each test and use portable paths/APIs. Fast and
  portable integration tests must work on macOS and Windows. Native Windows
  checks do not certify a macOS sandbox. See [test guide](tests/README.md).
