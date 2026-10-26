# AmbER eval data contract

The source is the `data/human/amber_set_tuples.jsonl` file from
[AmbER Sets](https://github.com/anthonywchen/AmbER-Sets), pinned by commit and
SHA-256 in `manifest.json`. AmbER data is CC0-1.0; upstream code is Apache-2.0.

`scripts/prepare_amber_eval.py` downloads that file and deterministically
selects 50 ambiguous names. For every name it chooses one popular head entity
and one less-popular tail entity with two single-valued properties.

The generated database contains entity, fact, and fact-alias tables without
foreign keys. A generated dossier states the ambiguous name and one clue alias,
but omits the entity QID and target fact. Its question asks for another
property. Gold evidence consists of the dossier URI and target fact-row URI.

The first 25 names form dev; the other 25 form the untouched test split. All
generated data is written under `cache/amber-eval/` and is not committed.
