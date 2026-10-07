# Documentation

- [Architecture overview](docs/architecture/Overview.md)
- [Architecture documents](docs/architecture/)
- [Repository layout](docs/repository-layout.md)

# Engineering Principles

- Keep interfaces and data models minimal and elegant: every field, parameter, and option must have a current purpose.

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
