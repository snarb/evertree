# Program lifecycle scenarios

End-to-end scenarios for writing and changing Programs of every kind in the
[Process Plane](../../docs/architecture/Process%20Plane/Process%20Plane%20Overview.md):
new Programs, improvements of the active one, competing implementations and alternative
solution principles, for `exec`, `model`, policy and `meta` Programs. Together they cover
the common paths through [Program Lifecycle](../../docs/architecture/Process%20Plane/Program%20Lifecycle%20and%20Evolution.md):
most real requests are PLC-01, 02, 03, 06 and 08; the rest cover the structural variants.
PLC-12 to PLC-16 cover model Programs as the agent's world model: the forecasts and
learnable estimators a Program declares in `LEARNING`, an exec Program acting on its model's
forecast, and the outcomes that train exactly the estimator a forecast used.

Each case in `cases.json` has:

- `setup`: seed Programs installed through the real gates (`programs`), new Program slots
  the developer declares (`proposals`), seeded Programs to use (`existing`), developer
  holdouts (`bindings`, with `history` for meta Programs), live runs whose outcomes
  the host reports later (`experience`) and exec runs whose forecasts the host already
  scored and learned from (`trained`);
- `task`: the request the live conscious agent receives, with `{key}` placeholders for ids;
- `mirror.steps`: the lifecycle calls the native mirror replays, with the files its
  scripted coding agent writes and the refusals it must meet (`error`);
- `outcomes`: outcomes the host reports after the probes, scored against the probes'
  forecasts and learned through `EverTree.learn_outcome`;
- `expect`: structural checks from `tests/support/lifecycle.py`; `mode` limits a check to
  `live` or `mirror`.

| ID | Scenario | Key checks |
| --- | --- | --- |
| PLC-01 | New exec Program from scratch | Slot set, `activate_program`, branch decisions refused for a new Program, probe |
| PLC-02 | Improve the active exec Program after an observed failure | Revision changed, `merge_branch`, accuracy above baseline, probes |
| PLC-03 | Requested change breaks the protected contract | No merge, rejection; mirror: direct `ctx` call and failing unit tests are refused |
| PLC-04 | Two competing branches of one claim | Same holdout, one merge, the other archived; mirror: dominated candidate cannot merge |
| PLC-05 | Alternative Program with a different principle | Slot moves to the alternative, the old Program becomes a candidate; mirror: kept alternative pauses at task end and its refresh conflicts |
| PLC-06 | Model Program on a proper score | Brier improves; mirror: a model that takes an action fails its contract |
| PLC-07 | Policy returning an ActionDistribution | Expected utility improves, best choice; mirror: unnormalized distribution and missing `PolicyDesign` are refused |
| PLC-08 | ProgramImprovement (exec+meta) improves another Program | Meta run completes and merges; mirror: non-meta `program.*` and self-targeting are refused |
| PLC-09 | Change a meta Program | Candidate that regresses `history:accuracy` is refused, the other merges |
| PLC-10 | Holdout derived from unseen live outcomes | Three derived and sealed cases, the surfaced outcome excluded, sealed outcomes not recalled |
| PLC-11 | Main moves under an evaluated candidate | Second merge refused, refreshed, recertified on its holdout and merged |
| PLC-12 | New model Program with declared target and estimators | Activated; Core creates the target and `PROCESS_VARIABLE`; two bindings owned by the Program, estimators untrained; probes return the priors |
| PLC-13 | Exec Program acts on its model's forecast | `predict` indexes `PREDICTS`; the reported outcome is scored and updates only the estimator the forecast read |
| PLC-14 | Alternative model with a rate per carrier | Brier improves; slot moves; the displaced model's binding is released, its trained state kept |
| PLC-15 | Forecast contract for a distribution | Contract declared and met, merged; mirror: unnormalized forecasts and a metric unfit for the form fail `contracts` |
| PLC-16 | Revise a trained model | Derived and sealed model outcomes; merged revision keeps the trained state; mirror: a changed prior would start a new state |

```sh
# Mirror: real Git, native workers and protected evaluation; scripted coding (CI, macOS/Windows)
uv run pytest tests/native/test_lifecycle_mirror.py -q -n 0
# Live: the real agent and coding provider; run sequentially, two workers already hit HTTP 429
EVERTREE_CODEX_INTEGRATION=1 uv run pytest tests/lifecycle -q -n 0 -o tmp_path_retention_policy=all
# One live case in the debugger or terminal; artifacts in tmp/debug-lifecycle/<run>/
uv run python -m evertree.debug_lifecycle PLC-02
```

A rate-limited final model call ends the task as failed; the case then reruns from scratch
once after a pause. A task that used up its step budget is continued twice, as a user would.
Each live case writes `state.json` (Programs, branches, receipts, choices, bindings,
probes) and `failures.json` under its pytest directory, also on failure. Model work
varies, so checks bound counts, compare metrics with baselines and probe the active
code instead of fixing exact candidates.
