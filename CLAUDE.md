@AGENTS.md

## Live end-to-end runs (real Codex and Redis)

- Debug harnesses (`python -m evertree.debug_integration`, `python -m evertree.debug_evidence_assessment [scenario]`) need `EVERTREE_REDIS_URL` and `OPENAI_API_KEY`. The git-ignored `.env` lives in the main checkout root, not in a worktree, so load it without printing it: `(set -a; . <main-repo-root>/.env; set +a; uv run python -m <module> ...)`. Codex must already be signed in.
- Run them as background Bash commands writing to the scratchpad directory, ending the command with `echo done >> <log>`; wait with Monitor on `until grep -q '^done$' <log>`, never `sleep` in the foreground (blocked). Do not use `/tmp` for logs.
- Read logs with `grep -vE '^\s+(→|⚙)' <log>` to drop tool-call noise. Artifacts (graph, trace, beliefs, model prompts) are in `tmp/debug-*/<run>/`.
- If the first line of the log asks for Redis/OpenAI variables, the `.env` was not loaded; fix the environment and rerun, do not edit the harness.
