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

The baseline has all of the data. It can inspect the schema, execute any
read-only SQL query, and search all 10,000 files. Joinhound gets one
`get_context` tool. Both arms use the same model and may make eight tool calls.

The deterministic comparison is narrower. Both arms use the same seed search.
The flat arm stops after one hop; joinhound can traverse five hops. This
measures the recall, precision, and latency cost of graph expansion.

## Interpretation

Higher recall alone is not sufficient. A useful result needs better final
answer recall or confirmed-answer rate without an unreasonable precision,
latency, or token penalty. If the SQL-plus-search agent ties or wins, this eval
does not support claiming that joinhound improves answer quality.

## Recorded test run

The untouched test split was run on 2026-10-22. Retrieval used all 250 test
questions. The agent comparison used a balanced 50-question sample and
`claude-sonnet-5-5`.

| Retrieval | Recall | Precision | Mean latency |
| --- | ---: | ---: | ---: |
| One hop | 0.700 | 0.403 | 105 ms |
| Joinhound, five hops | 0.998 | 0.011 | 333 ms |

Joinhound recovered nearly every gold source, including the row beyond a case
file. It also returned a large graph: precision fell from 40.3% to 1.1%, and
latency was 3.2 times higher. One of fifty file-to-member retrieval questions
missed the user row.

| Agent | Answer recall | Confirmed | Tool calls | Mean latency | Input tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL + all-file search | 1.000 | 1.000 | 2.64 | 6.07 s | 157,145 |
| Joinhound | 1.000 | 1.000 | 1.00 | 5.11 s | 1,855,661 |

Both agents answered every sampled test question. Joinhound needed one tool
call and was 16% faster, but sent 11.8 times as many input tokens because the
low-precision graph was included in the model context.

This run does **not** show better answer quality with joinhound. It shows a
retrieval-recall and orchestration advantage offset by severe precision and
context-size costs. The next product work should reduce returned neighbors and
serialized graph size; this benchmark can then be rerun without changing the
test questions.
