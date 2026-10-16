# SPDX-License-Identifier: Apache-2.0

"""Apache Ossie documents. The file text is kept when the links do not change."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft202012Validator

from joinhound.core.models import LinkDraft
from joinhound.profiler.profile import link_id

_SCHEMA = Draft202012Validator(
    cast(dict[str, Any], json.loads(Path(__file__).with_name("ossie-schema.json").read_text()))
)
_ORIGIN = "ossie_import"
_VENDOR = "JOINHOUND"


class ModelError(ValueError):
    """An Ossie document cannot be read or written."""


class OssieFormat:
    """Validate an Ossie model and return it without dropping fields."""

    def load(self, text: str) -> str:
        """Validate model text and return its canonical YAML."""
        return _canonical(parse_document(text))

    def dump(self, text: str) -> str:
        """Serialize a model without dropping unknown fields."""
        return self.load(text)


def parse_document(text: str) -> dict[str, Any]:
    """Load a YAML or JSON object and validate it against the pinned schema."""
    stripped = text.lstrip()
    if not stripped:
        raise ModelError("Ossie model is empty")
    loaded: object = json.loads(text) if stripped.startswith("{") else yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ModelError("Ossie model must be a mapping")
    document = cast(dict[str, Any], loaded)
    errors = sorted(_SCHEMA.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ModelError(errors[0].message)
    return document


def links_from_document(document: dict[str, Any]) -> list[LinkDraft]:
    """Read approved relationships and JOINHOUND links from a document."""
    datasets = {
        str(dataset["name"]): dataset
        for dataset in cast(list[dict[str, Any]], document.get("datasets") or [])
    }
    drafts = [
        _relationship_draft(document, datasets, relationship)
        for relationship in cast(list[dict[str, Any]], document.get("relationships") or [])
    ]
    drafts.extend(_extension_drafts(document, datasets))
    return [draft for draft in drafts if draft is not None]


def apply_links(document: dict[str, Any], drafts: list[LinkDraft]) -> dict[str, Any]:
    """Return a document whose standard relationships and JOINHOUND links match drafts."""
    updated = copy.deepcopy(document)
    _sync_relationships(updated, drafts)
    if _joinhound_changed(document, drafts):
        _write_joinhound(updated, drafts)
    return updated


def _relationship_draft(
    document: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
    relationship: dict[str, Any],
) -> LinkDraft | None:
    del document
    from_columns = _strings(relationship.get("from_columns"))
    to_columns = _strings(relationship.get("to_columns"))
    if len(from_columns) != 1 or len(to_columns) != 1:
        return None
    source = datasets[str(relationship["from"])]
    destination = datasets[str(relationship["to"])]
    src_collection = collection_of(source)
    dst_collection = collection_of(destination)
    return LinkDraft(
        link_id=link_id(src_collection, from_columns[0], dst_collection, to_columns[0]),
        src_collection=src_collection,
        src_column=from_columns[0],
        dst_collection=dst_collection,
        dst_column=to_columns[0],
        match_type="exact",
        origin=_ORIGIN,
        confidence=1.0,
        cardinality="N:1",
        status="approved",
        relation_name=str(relationship["name"]),
    )


def _extension_drafts(
    document: dict[str, Any],
    datasets: dict[str, dict[str, Any]],
) -> list[LinkDraft]:
    drafts: list[LinkDraft] = []
    for extension in cast(list[dict[str, Any]], document.get("custom_extensions") or []):
        if extension.get("vendor_name") != _VENDOR:
            continue
        payload = json.loads(str(extension["data"]))
        if not isinstance(payload, dict):
            raise ModelError("JOINHOUND extension data must be a JSON object")
        links = cast(list[object], payload.get("links") or [])
        for item in links:
            if not isinstance(item, dict):
                raise ModelError("JOINHOUND links must be JSON objects")
            drafts.append(_extension_draft(datasets, cast(dict[str, Any], item)))
    return drafts


def _extension_draft(datasets: dict[str, dict[str, Any]], item: dict[str, Any]) -> LinkDraft:
    src_name, src_column = _split_field(str(item["from"]), datasets)
    source = datasets[src_name]
    dst_column: str | None
    if "to_collection" in item:
        dst_collection = str(item["to_collection"])
        dst_column = None
        dst_name = dst_collection
    else:
        dst_name, dst_column = _split_field(str(item["to"]), datasets)
        dst_collection = collection_of(datasets[dst_name])
    confidence = item.get("confidence", 1.0)
    normalize = item.get("normalize_sql")
    return LinkDraft(
        link_id=str(item["id"]),
        src_collection=collection_of(source),
        src_column=src_column,
        dst_collection=dst_collection,
        dst_column=dst_column,
        match_type=str(item["match"]),
        origin=_ORIGIN,
        confidence=float(cast(float, confidence)),
        normalize_sql=None if normalize is None else str(normalize),
        status=str(item.get("status") or "proposed"),
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in cast(list[object], value)]


def collection_of(dataset: dict[str, Any]) -> str:
    """Map a dataset source to a collection id. `main.public.orders` is `pg://main/public.orders`."""
    source = str(dataset.get("source") or dataset["name"])
    if "://" in source:
        return source
    parts = source.split(".")
    if len(parts) >= 3:
        return f"pg://{parts[0]}/{parts[1]}.{'.'.join(parts[2:])}"
    return source


def _sync_relationships(document: dict[str, Any], drafts: list[LinkDraft]) -> None:
    relationships = cast(list[dict[str, Any]], document.get("relationships") or [])
    wanted = {
        key
        for draft in drafts
        if _is_standard(draft)
        for key in (_draft_key(document, draft),)
        if key is not None
    }
    rebuilt: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for relationship in relationships:
        key = _relationship_key(relationship)
        if key is None or key in wanted:
            rebuilt.append(relationship)
            if key is not None:
                seen.add(key)
    for draft in drafts:
        if not _is_standard(draft):
            continue
        key = _draft_key(document, draft)
        if key is None or key in seen:
            continue
        src_name, src_column, dst_name, dst_column = key
        rebuilt.append(
            {
                "name": draft.relation_name or f"{src_name}_to_{dst_name}",
                "from": src_name,
                "to": dst_name,
                "from_columns": [src_column],
                "to_columns": [dst_column],
            }
        )
        seen.add(key)
    if rebuilt != relationships:
        document["relationships"] = rebuilt


def _joinhound_changed(document: dict[str, Any], drafts: list[LinkDraft]) -> bool:
    current = _joinhound_links(document)
    wanted = [draft for draft in drafts if not _is_standard(draft)]
    if len(current) != len(wanted):
        return True
    by_id = {str(item.get("id")): item for item in current}
    return any(not _same_extension(by_id.get(draft.link_id), draft, document) for draft in wanted)


def _write_joinhound(document: dict[str, Any], drafts: list[LinkDraft]) -> None:
    extensions = [
        extension
        for extension in cast(list[dict[str, Any]], document.get("custom_extensions") or [])
        if extension.get("vendor_name") != _VENDOR
    ]
    links = [_extension_item(document, draft) for draft in drafts if not _is_standard(draft)]
    if links:
        extensions.append(
            {
                "vendor_name": _VENDOR,
                "data": json.dumps({"links": links}, ensure_ascii=False),
            }
        )
    if extensions:
        document["custom_extensions"] = extensions
    else:
        document.pop("custom_extensions", None)


def _extension_item(document: dict[str, Any], draft: LinkDraft) -> dict[str, Any]:
    src_name = _dataset_name(document, draft.src_collection)
    item: dict[str, Any] = {
        "id": draft.link_id,
        "status": draft.status,
        "match": draft.match_type,
        "from": f"{src_name}.{draft.src_column}",
        "confidence": draft.confidence,
    }
    if draft.dst_column is None:
        item["to_collection"] = draft.dst_collection
    else:
        dst_name = _dataset_name(document, draft.dst_collection)
        item["to"] = f"{dst_name}.{draft.dst_column}"
    if draft.normalize_sql is not None:
        item["normalize_sql"] = draft.normalize_sql
    return item


def _same_extension(
    item: dict[str, Any] | None,
    draft: LinkDraft,
    document: dict[str, Any],
) -> bool:
    if item is None:
        return False
    expected = _extension_item(document, draft)
    return all(item.get(key) == value for key, value in expected.items())


def _joinhound_links(document: dict[str, Any]) -> list[dict[str, Any]]:
    for extension in cast(list[dict[str, Any]], document.get("custom_extensions") or []):
        if extension.get("vendor_name") != _VENDOR:
            continue
        payload = json.loads(str(extension["data"]))
        if isinstance(payload, dict):
            return [
                cast(dict[str, Any], item)
                for item in cast(list[object], payload.get("links") or [])
                if isinstance(item, dict)
            ]
    return []


def _is_standard(draft: LinkDraft) -> bool:
    return (
        draft.status == "approved"
        and draft.dst_column is not None
        and draft.match_type in {"declared_fk", "exact"}
    )


def _relationship_key(relationship: dict[str, Any]) -> tuple[str, str, str, str] | None:
    from_columns = cast(list[object], relationship.get("from_columns") or [])
    to_columns = cast(list[object], relationship.get("to_columns") or [])
    if len(from_columns) != 1 or len(to_columns) != 1:
        return None
    return (
        str(relationship["from"]),
        str(from_columns[0]),
        str(relationship["to"]),
        str(to_columns[0]),
    )


def _draft_key(
    document: dict[str, Any],
    draft: LinkDraft,
) -> tuple[str, str, str, str] | None:
    if draft.dst_column is None:
        return None
    src_name = _dataset_name(document, draft.src_collection)
    dst_name = _dataset_name(document, draft.dst_collection)
    if src_name is None or dst_name is None:
        return None
    return (src_name, draft.src_column, dst_name, draft.dst_column)


def _dataset_name(document: dict[str, Any], collection_id: str) -> str | None:
    for dataset in cast(list[dict[str, Any]], document.get("datasets") or []):
        if collection_of(dataset) == collection_id:
            return str(dataset["name"])
    return None


def _split_field(token: str, datasets: dict[str, dict[str, Any]]) -> tuple[str, str]:
    for name in sorted(datasets, key=len, reverse=True):
        prefix = f"{name}."
        if token.startswith(prefix):
            return name, token[len(prefix) :]
    dataset, separator, column = token.partition(".")
    if not separator or not column:
        raise ModelError(f"Ossie field must be dataset.column: {token}")
    return dataset, column


def _canonical(document: dict[str, Any]) -> str:
    dumped = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=10**6)
    return dumped if dumped.endswith("\n") else f"{dumped}\n"
