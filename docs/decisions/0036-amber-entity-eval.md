# 0036. Evaluate ambiguous entities with CC0 AmbER data

## Context

The library evaluation has explicit foreign keys and a small, clear schema. A
strong model can search a note, write the complete SQL join, and answer every
question without joinhound. That result does not exercise the product's
claimed advantage on undeclared and cross-source links.

AmbER Sets is an established entity-disambiguation benchmark. Its data is CC0
and groups Wikidata entities that share a displayed name. The repository also
contains properties and answer aliases for each entity.

## Decision

Add a separate AmbER database-and-files evaluation pinned to upstream commit
`fc8415e411998a6232b5cb9f0f71f29b7591b6af`.

The preparation script selects 50 ambiguous names with a usable head and tail
entity. It creates:

- relational entity, fact, and fact-alias tables without foreign keys;
- one dossier for each selected entity, containing the ambiguous name and one
  distinguishing fact alias but not its QID or requested answer;
- one question per dossier asking for another property;
- gold provenance for both the dossier and the answer row.

The tables retain value-level identifiers from AmbER, but their relationships
are not declared in the source catalog. Approved eval links connect fact
aliases to facts, facts to entities, and dossier mentions to rows. The direct
arm receives the schema, unrestricted read-only SQL, and search over every
dossier. The joinhound arm receives those same tools plus `get_context`,
`expand`, and `get_record`. Both arms use the same model, random arm order,
and an eight-call limit. `--access files` removes SQL from both arms.
`--access blind` keeps SQL and replaces the join hint with the public column
list. Those two runs are recorded in `docs/eval/amber.md`.

Generated tables and files remain in `cache/`. The repository stores only the
pinned URL, SHA-256, preparation code, question contract, and documentation.

## Alternatives

- Use DailyMed labels and the FDA Orange Book. They are authoritative public
  data, but application numbers make most joins explicit and monthly releases
  are mutable.
- Use DWIE or AIDA-CoNLL. DWIE is GPL-3.0, while full AIDA Reuters text has
  redistribution restrictions.
- Limit the direct arm to four tool calls. A smoke run showed this can make SQL
  time out while joinhound answers, but the constraint manufactures an
  advantage and is not the primary comparison.
