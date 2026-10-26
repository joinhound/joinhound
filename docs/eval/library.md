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

`--limit` must be a multiple of the number of question kinds so each kind has
equal weight. The standard suite has five kinds. The hard suite does too. Use
`--suite hard` to load `hard.json`. Use the dev split while changing retrieval
or prompts. Report the untouched test split once.

## What is fair here

Both arms can inspect the schema, execute any read-only SQL query, and search
all 10,000 files. The joinhound arm additionally gets `get_context`, `expand`,
and `get_record`. Both arms use the same model and may make eight tool calls.
Their execution order is randomized per question. `get_context` returns a
bounded set of paths rather than every neighbor that fits the token budget.

The deterministic comparison is narrower. Both arms use the same seed search.
The flat arm stops after one hop; joinhound can traverse five hops. This
measures the recall, precision, and latency cost of graph expansion.

## Interpretation

Higher recall alone is not sufficient. A useful result needs better final
answer recall or confirmed-answer rate without an unreasonable precision,
latency, or token penalty. If the SQL-plus-search agent ties or wins, this eval
does not support claiming that joinhound improves answer quality.

## Recorded dev run

These figures are from the dev split on 2026-10-22, after the path budget, protected forward chain, and sentence-level note search. They are tuning measurements. The untouched test split has not been rerun.

Standard dev, all 250 questions:

| Retrieval | Recall | Precision | Mean latency |
| --- | ---: | ---: | ---: |
| One hop | 0.700 | 0.270 | 100 ms |
| Joinhound, five hops | 0.990 | 0.109 | 310 ms |

Joinhound recall by kind: database 1.00 and documents 1.00, the same as one hop on those kinds. File-to-book is 1.00 against 0.50, file-to-branch 0.98 against 0.50, and file-to-member 0.97 against 0.50. One hop already finds the member named by a library card, and it does so in a smaller graph: database precision is 0.100 for one hop and 0.057 for five hops.

Hard dev, all 125 questions:

| Retrieval | Recall | Precision | Mean latency |
| --- | ---: | ---: | ---: |
| One hop | 0.500 | 0.275 | 121 ms |
| Joinhound, five hops | 0.956 | 0.150 | 332 ms |

Paraphrased member, paraphrased book, rejected-name, and publisher questions all reach 1.00 recall. The publisher is five links from the note. Staff questions, which answer with the user linked from the staff profile, reach 0.78. One hop stays at 0.50 because it finds the note and not the later row. Five hops returns the answer inside a path of about seven to fifteen nodes, so precision stays near 0.15 while one hop, which usually returns only the note, is more precise.

Hard dev agent comparison, the same 125 questions, both arms with schema inspection, read-only SQL, and file search. The joinhound arm also has `get_context`, `expand`, and `get_record`. Order is randomized per question. Maximum eight tool calls.

| Arm | Answer recall | Confirmed | Mean tool calls | Mean latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL and file search | 1.000 | 1.000 | 3.0 | 6871 ms | 475,720 |
| Same tools plus joinhound | 1.000 | 1.000 | 3.0 | 5351 ms | 594,464 |

Every question was answered correctly by both arms, and every answer was present in the tool output. Joinhound used about 25% more prompt tokens and was faster on average. The test split was left untouched because this dev run does not show an answer-quality gain.
