# Evidence assessment cases

End-to-end cases for belief data, built from text. Each case in `cases.json` feeds user messages, observations and documents step by step. After every step, the real KnowledgeIntegration and EvidenceAssessment Programs run with a real Codex model, Redis Search and OpenAI embeddings. Expectations are then checked on the belief snapshot taken after the step.

Model judgement varies between runs, so expectations are ordinal (`down`, `same`, `> 0.5`, `A > B`), not exact numbers. Integration chooses its own wording, so elements are selected by kind and by keywords that survive translation: ids such as `Н-4` and numbers. An `optional` expectation passes when integration did not create the element it describes.

Deterministic contracts of the same mechanisms (scripted model, real stores) are in `tests/component/test_graph_evidence_assessment.py`.

## Running

The suite is selected only explicitly and needs the live opt-in plus search credentials. The git-ignored `.env` lives in the main checkout root, not in a worktree:

```sh
(set -a; . <main-checkout>/.env; set +a; \
 EVERTREE_CODEX_INTEGRATION=1 uv run pytest tests/evidence -q -n 2 \
   --basetemp=tmp/evidence-cases -o tmp_path_retention_policy=all)
```

At most two workers: more hit the model's rate limit (HTTP 429). A case usually takes 0.5–3 minutes (two model calls per step, integration and assessment, plus integration's graph tools); a full run takes about half an hour and uses account resources. A rate-limited or stalled call (over 5 minutes) reruns the case from scratch after a pause, up to three attempts, each in its own `attempt-N` directory. Each case directory keeps `history.json` (beliefs and origin reliabilities after each step, plus failed expectations), `graph.json`, `trace.json`, `beliefs.json`, `evidence.json` and the model transcripts. Run one case with `-k <id>`, or step through it in the debugger with `python -m evertree.debug_evidence_assessment <id>`.

## Expectation forms

| Form | Meaning |
| --- | --- |
| `{"at": n, "select": S, "strength": [op, x]}` | after step `n`, a selected element (`"mode": "all"`: every one) satisfies the bound; also `support`, `evidence_count`; `op` is `<`, `<=`, `>`, `>=`, `==` or `between` |
| `{"change": [m, n], "select": S, "strength": "up"}` | the field moved `up`, `down` or stayed the `same` (±0.01) between steps for an element present at both |
| `{"at": n, "compare": [S1, ">", S2]}` | the strongest match of `S1` against the strongest of `S2` |
| `{"at": n, "origin": "sensor:T-7", "reliability": [op, x]}` | reliability belief of a source origin |
| `{"at": n, "scope": [S1, S2, …]}` | one match of each selector belongs to one competition scope, and their probabilities sum to at most 1 |

A selector `S` is `{"kind" or "kinds", "all": [term or [any-of terms]], "none": [terms], "in_scope"?: true}`, matched case-insensitively against the element's name, its description and, for a relation fact, its relation type and participants.

## Scenario catalog

| ID | Scenario | Case |
| --- | --- | --- |
| A1 | Claim: a hedged causal hypothesis gains from a sensor, loses to an inspection report | `claim-hypothesis-tested` |
| A2 | Note: a preserved generalisation is contradicted by an incident log | `note-checked-against-log` |
| A3 | Relation: part-whole membership contradicted by a schematic | `relation-part-whole-contradicted` |
| A4 | Facet: states with intervals; the user corrects an interval | `facet-interval-correction` |
| A5, A6 | Prototype/Concept definition challenged by a counterexample | `prototype-definition-counterexample` |
| A7 | Classification contradicted by an equipment passport | `classification-corrected-by-passport` |
| A8 | Numeric value contradicted, unaffected by another object's reading, corrected | `numeric-setpoint-correction` |
| S1–S3, S5, S9 | Independent confirmation, self-repetition, contradiction, hedged doubt | `location-confirm-repeat-contradict` |
| B1, D1 | Reposts of one rumour are one source; a peer-reviewed trial outweighs it | `reposts-vs-peer-reviewed-study` |
| B2 | Independent anonymous comments versus one manufacturer bulletin | `independent-weak-sources-vs-bulletin` |
| B3, B4 | A sensor found faulty weakens every fact resting on it; clearing it restores them | `discredited-sensor-then-rehabilitated` |
| B5 | The user withdraws a statement and then reasserts it | `retraction-and-reassertion` |
| C1, C3 | Mutually exclusive causes compete; a new alternative versions the scope | `failure-cause-hypotheses` |
| C2 | Two simultaneous locations of one object are exclusive | `categorical-location` |
| E1 | A later state change does not contradict an earlier state | `state-succession-not-contradiction` |
| F1 | One failure barely bears on a general reliability claim | `instance-failure-vs-generalisation` |
| F2 | A pattern stated later is supported by earlier integrated observations | `pattern-from-earlier-observations` |
| G1, G2 | A question and a counterfactual assert nothing | `question-and-hypothetical-are-not-evidence` |
| G3 | Unverified hearsay is weak; a measurement overturns it | `hearsay-then-measurement` |
| G4 | An instruction ("remember…") is not evidence | every case: the task message is never counted |

Not yet covered by a case, and not implemented: reliability scoped to a domain or a time window (a sensor faulty only since a date), and structural revision of a scope whose alternatives turn out to be compatible. Unit and component tests cover redelivery of the same observation (S11) and malformed model output (S12).
