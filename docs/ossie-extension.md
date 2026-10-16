# JOINHOUND Ossie extension

Joinhound reads and writes [Apache Ossie](https://github.com/apache/ossie) semantic models. Equality relationships with cardinality N:1 stay in the standard `relationships` list. Every other relationship is a JSON object inside a model-level custom extension.

```yaml
custom_extensions:
  - vendor_name: JOINHOUND
    data: '{"links":[ ... ]}'
```

`vendor_name` is the string `JOINHOUND`. `data` is a JSON object, serialized as a string, with one key, `links`. Other vendors' extensions on the same document are left in place.

## One link

| Field | Meaning |
| --- | --- |
| `id` | Stable link id. Import uses it to update the same row. |
| `status` | `proposed`, `approved`, or `rejected`. |
| `match` | `normalized`, `fuzzy`, `semantic`, `column_documents`, or another non-equality type. |
| `from` | `dataset.column` in this model. |
| `to` | `dataset.column` when the destination is a column. |
| `to_collection` | Collection URI when the destination is a document collection. |
| `confidence` | Number from 0 to 1. |
| `normalize_sql` | Name of a library expression, present only for `normalized`. |

`to` and `to_collection` are alternatives. A column destination uses `to`. A document destination uses `to_collection`.

```json
{
  "id": "orders.customer_email__customers.email",
  "status": "proposed",
  "match": "normalized",
  "from": "orders.customer_email",
  "to": "customers.email",
  "normalize_sql": "fold",
  "confidence": 0.97
}
```

```json
{
  "id": "products.code__specs",
  "status": "approved",
  "match": "exact",
  "from": "products.code",
  "to_collection": "s3://specs/",
  "confidence": 0.93
}
```

## Round trip

`joinhound import ossie model.yaml` stores standard relationships as approved. Extension links keep the `status` in the file. Both are stored with `origin = ossie_import`. `joinhound profile` does not rediscover those links. `joinhound export ossie --out model.yaml` writes the current links back. Metrics, unknown fields, and other vendors' extensions are copied through unchanged.

Approved N:1 equality links move into standard `relationships` on export. Edit `status` in the extension, or accept the file in review, then import again.
