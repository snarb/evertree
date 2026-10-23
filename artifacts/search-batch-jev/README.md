# Batch search and Jev validation — 2026-10-21

Historical result: the recall estimate below used repeated category placements and
summary-only article cards. It is not a general estimate of search quality. See the
[recall investigation](../search-recall/README.md) for the corrected corpus, stage-by-stage
losses and later measurements. Numbers below remain unchanged for auditability.

Twenty new sports queries were selected with seed `20261021`. None of their query
indices or complete gold URL groups appears in the train/validation/test splits
of commit `0abaa54`. Documents remain a shared retrieval corpus, not a document
holdout. The current search pipeline ran over 1,369 imported title/summary cards
plus bootstrap objects, with the production 7/12 quotas and ten-per-query limit.
The Jev model and threshold were frozen before evaluation: `jev-1.13.0`, `0.05`.

| Mode | Search calls | Total seconds | Gold URL recall | Gold URL precision |
| --- | ---: | ---: | ---: | ---: |
| Singleton, Jev off | 20 | 5.819 | 20/37 (54.05%) | 20/56 (35.71%) |
| Batches of four, Jev off | 5 | 1.618 | 20/37 (54.05%) | 20/56 (35.71%) |
| Singleton, Jev on | 20 | 10.867 | 20/37 (54.05%) | 20/56 (35.71%) |
| Batches of four, Jev on | 5 | 3.862 | 20/37 (54.05%) | 20/54 (37.04%) |

Jev preserved **20/20 relevant raw candidate URLs** before truncation in the
singleton run, meeting the observed ≥99% retention target. Raw candidate retention
was not separately measured per query inside batch unions; end-to-end batch recall
was unchanged. All searches completed, with no Jev fallback warnings. The default
threshold remains `0.05`; no threshold was selected or tuned on these outcomes.

The missing 17 gold URLs were absent from the initial singleton candidate pools.
These results do not establish 99% end-to-end recall: retrieval coverage is the
current bottleneck. Twenty retained positives are a small sample and cannot
establish a universal 99% retention guarantee. Precision counts unique returned
article URLs against supplied gold labels; category cards and duplicate article
placements are excluded from these URL metrics.

Timing is one warm-index run per mode on the same interpreter and machine. It
includes query embeddings, Redis, optional Jev, Core rendering and small evidence
file writes; excludes initial corpus embeddings and LLM planning/tool round trips.
Runs were sequential in the table's order, without query-embedding caching. Other
integration tests ran concurrently, so timings are measurements, not an SLA.
Batching was 3.60× faster without Jev and 2.81× faster with Jev in this run.

`manifest.json` freezes corpus hashes, query selection and the implementation hash.
`results.json` retains per-query gold/returned URLs, singleton raw/retained relevant
URLs and every search status/warning. `summary.json` contains the aggregates.

To repeat using existing `.env` credentials and a private Redis namespace:

```sh
PYTHONPATH=. uv run python artifacts/search-batch-jev/evaluate.py \
  --source /path/to/semgraph \
  --pilot /path/to/search-flat-jev/evertree/artifacts/search-flat \
  --output tmp/search-batch-jev-evaluation
```

The command sends corpus cards and queries to OpenAI embeddings and Typesafe/Jev
and can incur API costs. It removes only its own derived Redis namespace.

Mechanical verification: **810 fast tests**, **160 integration tests** including
real Redis Search, and **6 affected native runtime/Program tests** passed. Lint,
formatting and Program layout validation passed. Live metrics above are separate
from scripted protocol tests.
