# Library effectiveness comparison

This is the decision eval for whether joinhound improves retrieval or final
answers. It uses 176,780 CC0 database rows, 10,000 generated case-note files,
and 500 balanced questions. See `tests/eval/library/README.md` for the data
contract.

## Run

Start an empty PostgreSQL database, then:

```console
uv run python scripts/prepare_library_eval.py --dsn "$EVAL_DSN"
uv run python scripts/run_library_eval.py \
  --dsn "$EVAL_DSN" \
  --mode retrieval \
  --split test \
  --limit 250 \
  --out cache/library-eval/retrieval-test.json
```

For the agent comparison, set `LLM_API_KEY`, `LLM_BASE_URL`, and `JUDGE_MODEL`.
An Anthropic key that is not scoped to one workspace also needs
`ANTHROPIC_WORKSPACE_ID`.

```console
uv run python scripts/run_library_eval.py \
  --dsn "$EVAL_DSN" \
  --mode agent \
  --split test \
  --limit 50 \
  --out cache/library-eval/agent-test.json
```

`--limit` must be a multiple of five so each question kind has equal weight.
Use the dev split while changing retrieval or prompts. Report the untouched test
split once.

## What is fair here

Both arms can inspect the schema, execute any read-only SQL query, and search
all 10,000 files. The joinhound arm additionally gets `get_context`. Both arms
use the same model and may make eight tool calls. Their execution order is
randomized per question.

The deterministic comparison is narrower. Both arms use the same seed search.
The flat arm stops after one hop; joinhound can traverse five hops. This
measures the recall, precision, and latency cost of graph expansion.

## Interpretation

Higher recall alone is not sufficient. A useful result needs better final
answer recall or confirmed-answer rate without an unreasonable precision,
latency, or token penalty. If the SQL-plus-search agent ties or wins, this eval
does not support claiming that joinhound improves answer quality.

## Recorded test run

The untouched retrieval test split was run on 2026-10-22 using all 250 test
questions.

| Retrieval | Recall | Precision | Mean latency |
| --- | ---: | ---: | ---: |
| One hop | 0.700 | 0.403 | 105 ms |
| Joinhound, five hops | 0.998 | 0.011 | 333 ms |

Joinhound recovered nearly every gold source, including the row beyond a case
file. It also returned a large graph: precision fell from 40.3% to 1.1%, and
latency was 3.2 times higher. One of fifty file-to-member retrieval questions
missed the user row.

An initial 50-question agent run gave the joinhound arm only `get_context`.
Although both arms could reach all data, that tested two different workflows
rather than the additive value of joinhound. Its figures are superseded and are
not reported as an effectiveness result. The corrected paired agent run must be
recorded before making an answer-quality, latency, tool-call, or token claim.
