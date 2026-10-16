# 0012. Do not depend on the apache-ossie package

## Context

T1.5 starts by deciding whether the official Python package in `apache/ossie` can import and export models. The package is `apache-ossie` 0.2.0.dev0. It is not published on PyPI. Its Pydantic models set `extra="forbid"`, so a field the models do not know is rejected. A dump also drops empty optional fields and does not preserve YAML comments. The round trip has to return the same document, including another vendor's `custom_extensions`.

## Decision

Validate with `jsonschema` 4.26.0 against `ossie-schema.json` from apache/ossie commit `95314296b725dcff503cf2eb92e89f7cf43c5a95`. The document stays a mapping, so metrics, descriptions, and other vendors' extensions are kept.

`joinhound import ossie` stores the file text and rebuilds `kg.links`. A dataset source `database.schema.table` becomes collection `pg://database/schema.table`. Standard relationships are approved `exact` links with origin `ossie_import`. The `JOINHOUND` extension keeps the link objects shown in the specification. `joinhound export ossie` writes the original text when those links still describe the same document. A changed link set is written as canonical YAML.

A relationship with more than one column is left in the document and is not turned into a `kg.links` row.

## Alternatives

- Depend on `apache-ossie` from a Git commit. Unknown fields would be rejected, and the dependency is an unreleased version.
- Rebuild every export from `kg.links` alone. Metrics and foreign extensions would disappear.
