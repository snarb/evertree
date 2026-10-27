# Evaluative-control scenarios

End-to-end scenarios for the signals of the
[Evaluative-Control System](../../docs/architecture/Evaluative-Control%20System.md), worked on
by the real conscious agent at the lifecycle stages where an agent meets them most:
finishing an ordinary Task, receiving supervisor feedback during and after work, diagnosing
explanatory tension and its coverage gaps, reporting deadline adherence, being cancelled
and reflecting on the signals. `component/test_evaluative_control.py` covers the
same contracts deterministically with a scripted model (EVC-01–26), and
`component/test_debug_evaluative_control.py` proves the harness offline.

Each case in `cases.json` has:

- `setup`: saved experience relative to the run's start: calibrated `tension` values and
  `omissions` per process (`days_ago` is the outcome time), `tasks` with outcomes, completion
  times and deadlines (a `name` makes the Task id available as `{name}` in the task text), and
  supervisor `feedback` on named Tasks;
- `task`: the request the live conscious agent receives, optionally with `deadline_minutes`
  and the working `process`;
- `during`: host events applied once the task has started: `feedback` or `cancel`;
- `expect`: structural checks from `tests/support/evaluative.py`: Task status and fields,
  completed tool calls with selected processes and result values, calibrated outcome checks
  with their basis, feedback results, host statistics, Program runs and facts in the answer.

| ID | Scenario | Key checks |
| --- | --- | --- |
| EVL-01 | Ordinary task | Succeeded; the TaskVerified forecast has a model-based bernoulli `prediction_unexpectedness`; success 1/1 |
| EVL-02 | Feedback during work | The comment ("answer in French") is followed; the feedback value is on the Task's process |
| EVL-03 | Feedback recall | `supervisor_feedback` is called; the answer gives the value and the stated reason |
| EVL-04 | Tension rise | `tension_reduction` on SelfTaskManagement is negative; SelfPlanning is named as the driver |
| EVL-05 | Broad reduction | Positive `tension_reduction` on SelfLearning; several components are named |
| EVL-06 | Coverage gaps | Skipped processes are reported with `cost_not_justified` and missing data |
| EVL-07 | Deadlines | `task_outcome_stats`: on time 1/3 with open overdue counted and early cancellation excluded; success 2/3 |
| EVL-08 | Task with a deadline | Submitted with a deadline and a process; counted on time |
| EVL-09 | Cancellation | Cancelled with its reason; no verification outcome; reported as a cancellation |
| EVL-10 | Reflection on signals | Statistics and tension are passed to SelfReflection under `evaluative_signals`; checkable hypotheses |

```sh
# Live: the real agent, sequentially (about an hour); parallel workers soon hit HTTP 429
EVERTREE_CODEX_INTEGRATION=1 uv run pytest tests/evaluative -q -n 0 -o tmp_path_retention_policy=all
# One case in the debugger or terminal; artifacts in tmp/debug-evaluative/<run>/
uv run python -m evertree.debug_evaluative_control EVL-04
```
