# AmbER ambiguous-entity evaluation

This eval uses the CC0 [AmbER Sets](https://github.com/anthonywchen/AmbER-Sets)
benchmark to test undeclared database relationships and cross-source entity
resolution. Preparation selects 50 names shared by multiple Wikidata entities,
then creates 94 entity rows, 196 fact rows, 1,520 fact-alias rows, and 100
dossier files.

Each dossier contains an ambiguous name and one distinguishing fact, but no QID
or requested answer. The question asks for a different property. Resolving it
requires dossier → alias/name → entity → target fact. The source tables have no
foreign keys.

## Run

Start an empty PostgreSQL database, then:

```console
uv run python scripts/prepare_amber_eval.py --dsn "$AMBER_EVAL_DSN"
uv run python scripts/run_amber_eval.py \
  --dsn "$AMBER_EVAL_DSN" \
  --mode retrieval \
  --split dev \
  --limit 50 \
  --out cache/amber-eval/retrieval-dev.json
```

For the paired agent run, set `LLM_API_KEY`, `LLM_BASE_URL`, and
`JUDGE_MODEL`, then use `--mode agent`. Both arms can inspect the schema,
execute read-only SQL, and search every dossier. The joinhound arm additionally
gets `get_context`, `expand`, and `get_record`. Arm order is randomized and
both arms may make eight tool calls.

A fuzzy suite writes the distinguishing clue with diacritics removed and two
letters transposed. The database keeps the canonical alias. Pass `--distort`
to preparation and point the runner at `cache/amber-eval/bundle-fuzzy`.

`--access` changes what both arms can see. `full` keeps SQL, dossier search,
and the join hint. `files` drops SQL and the schema tool, leaving dossier
search and, on the joinhound arm, `get_context`. `blind` keeps SQL and returns
only the public column list, without the sentence that a dossier identifies
the subject by one fact alias.

## Recorded dev run

These are tuning measurements on the 50-question dev split from 2026-10-22.
The 50-question test split remains untouched.

| Retrieval | Evidence recall | Precision | Mean latency |
| --- | ---: | ---: | ---: |
| One hop | 0.570 | 0.095 | 36 ms |
| Joinhound, four hops | 0.900 | 0.119 | 427 ms |

Four-hop recall is 0.96 for the more popular head entities and 0.84 for tail
entities. The engine discovers 49 of 50 target fact rows, but the bounded
response does not select every discovered tail fact.

Paired agent run with `claude-sonnet-5-5`:

| Arm | Answer recall | Confirmed | Mean tool calls | Mean latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL and dossier search | 1.000 | 1.000 | 3.28 | 7210 ms | 206,953 |
| Same tools plus joinhound | 1.000 | 1.000 | 3.12 | 5156 ms | 476,307 |

Both arms answered all 50 questions correctly with tool-confirmed evidence.
Joinhound was faster and used slightly fewer tool calls, but consumed 2.3 times
as many prompt tokens. This dataset therefore demonstrates a retrieval recall
gain, not a final-answer quality gain over direct SQL and file search.

## Compact chain and fuzzy clues

A later dev run asks `get_context` to return one chain whose field value is the
property named in the question. On the exact dossiers above, four-hop evidence
recall becomes 0.800 and precision 0.523 (head 0.94, tail 0.66, mean latency
429 ms). The wider response recorded above remains the comparison for that
exact suite.

The fuzzy suite keeps the same questions and canonical aliases, but the dossier
clue has its diacritics removed and two letters transposed. Preparation is
`scripts/prepare_amber_eval.py --distort`. The runner reads
`cache/amber-eval/bundle-fuzzy`. A read-only query that fails, or an arm that
uses eight tool calls without submitting an answer, scores as a miss for that
question.

Fuzzy dev retrieval after the compact chain keeps the asked value in 49 of 50
first responses. Mean context size is about 60 tokens.

`claude-sonnet-5-5` still answers every fuzzy dev question from either arm.
The SQL arm uses 216,210 prompt tokens and 3.4 calls. The joinhound arm uses
253,955 prompt tokens and 2.4 calls. `claude-haiku-4-5` does not tie that
result. On the same 50 questions:

| Arm | Answer recall | Confirmed | Mean tool calls | Mean latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL and dossier search | 0.220 | 0.040 | 1.90 | 3777 ms | 163,268 |
| Same tools plus joinhound | 0.980 | 0.980 | 1.16 | 2918 ms | 170,450 |

Forty-six of the joinhound answers used one tool call. The remaining miss is
the model shortening `association football` to `football`. The test split was
not run.

## Access modes on the fuzzy dev split

The same 50 fuzzy questions were run again with `claude-sonnet-5-5` after
removing either SQL or the join hint. The test split stayed untouched.

Dossiers only, no SQL:

| Arm | Answer recall | Confirmed | Mean tool calls | Mean latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dossier search | 0.280 | 0.120 | 4.34 | 9207 ms | 234,980 |
| Dossier search plus joinhound | 1.000 | 1.000 | 3.08 | 8288 ms | 398,966 |

Fourteen baseline answers contained the gold string. Six of those strings were
present in the dossier search output. The other eight were inferences from the
distorted clue, such as reading `fulblack` as a fullback and answering
`American football`. The remaining baseline answers say the dossier does not
state the property. Joinhound answered and confirmed all 50. It used 398,966
prompt tokens, more than the full-access SQL arm (216,210), because this arm
has no SQL path.

SQL with the column list and no join hint:

| Arm | Answer recall | Confirmed | Mean tool calls | Mean latency | Prompt tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQL and dossier search | 0.980 | 0.940 | 3.24 | 6152 ms | 218,619 |
| Same tools plus joinhound | 1.000 | 1.000 | 2.60 | 5551 ms | 267,590 |

The SQL arm missed one question by using all eight calls without an answer.
Column names were enough for Sonnet to reconstruct the joins on the other 49.
Joinhound stayed at 1.000 and used more prompt tokens.
