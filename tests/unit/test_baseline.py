# SPDX-License-Identifier: Apache-2.0

"""Cited provenance is scored against gold rows and against tool results."""

import json

from joinhound.core.uri import PgUri, build_uri
from joinhound.engine.baseline import (
    answer_confirmed,
    answer_recall,
    cited_keys,
    tables_in_sql,
    uris_from_rows,
)
from joinhound.engine.evaluate import record_key


def test_cited_uri_may_contain_a_json_key() -> None:
    film = build_uri(PgUri("pagila", "public", "film", {"film_id": 2}))
    answer = 'Film: pg://pagila/public.film#pk={"film_id":2}'

    assert cited_keys(answer) == {record_key(film)}
    assert answer_recall(answer, [film]) == 1.0
    assert cited_keys(json.dumps({"uri": film})) == {record_key(film)}


def test_answer_recall_counts_only_cited_gold_rows() -> None:
    film = build_uri(PgUri("pagila", "public", "film", {"film_id": 2}))
    actor = build_uri(PgUri("other", "public", "actor", {"actor_id": 19}))

    recall = answer_recall(f"ACE GOLDFINGER is {film}.", [film, actor])

    assert recall == 0.5
    assert answer_confirmed(f"See {film}.", {record_key(film)})
    assert not answer_confirmed("The cast is unknown.", {record_key(film)})
    assert cited_keys("no provenance") == set()


def test_sql_rows_become_uris_when_the_primary_key_is_selected() -> None:
    uris = uris_from_rows(
        [{"actor_id": 19, "first_name": "BOB"}],
        {"actor": ["actor_id"], "film": ["film_id"]},
        tables_in_sql("SELECT actor_id, first_name FROM public.actor a"),
    )

    assert [record_key(uri) for uri in uris] == [
        record_key(build_uri(PgUri("pagila", "public", "actor", {"actor_id": 19})))
    ]
