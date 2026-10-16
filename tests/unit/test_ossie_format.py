# SPDX-License-Identifier: Apache-2.0

"""Ossie load, dump, and link mapping without a database."""

import json
from pathlib import Path

import yaml

from joinhound.formats.ossie import OssieFormat, apply_links, links_from_document, parse_document

_TPC_DS = Path(__file__).parents[1] / "fixtures" / "tpcds_semantic_model.yaml"


def test_tpcds_round_trip_keeps_the_document_and_foreign_extensions() -> None:
    text = _TPC_DS.read_text(encoding="utf-8")
    canonical = OssieFormat().load(text)

    assert OssieFormat().dump(canonical) == canonical
    assert yaml.safe_load(canonical) == yaml.safe_load(text)
    document = parse_document(text)
    vendors = [item["vendor_name"] for item in document["custom_extensions"]]
    assert vendors == ["SALESFORCE", "DBT"]
    assert apply_links(document, links_from_document(document)) == document


def test_ai_context_extra_is_kept() -> None:
    text = """
version: "0.2.0.dev0"
name: shop
datasets:
  - name: orders
    source: main.public.orders
    ai_context:
      instructions: keep
      vendor_note: extra
"""
    loaded = yaml.safe_load(OssieFormat().load(text))

    assert loaded["datasets"][0]["ai_context"]["vendor_note"] == "extra"


def test_approved_extension_link_becomes_a_relationship() -> None:
    link = {
        "id": "orders.customer_id__customers.id",
        "status": "approved",
        "match": "exact",
        "from": "orders.customer_id",
        "to": "customers.id",
        "confidence": 1.0,
    }
    document = {
        "version": "0.2.0.dev0",
        "name": "shop",
        "datasets": [
            {"name": "orders", "source": "main.public.orders"},
            {"name": "customers", "source": "main.public.customers"},
        ],
        "custom_extensions": [
            {"vendor_name": "OTHER", "data": '{"kept": true}'},
            {"vendor_name": "JOINHOUND", "data": json.dumps({"links": [link]})},
        ],
    }
    updated = apply_links(document, links_from_document(document))

    assert updated["relationships"][0]["from"] == "orders"
    assert updated["relationships"][0]["to_columns"] == ["id"]
    assert [item["vendor_name"] for item in updated["custom_extensions"]] == ["OTHER"]
