# Configuration

One YAML file describes the process. `${NAME}` is replaced from the environment. An unknown key is an error. Secrets stay in the environment. They are not written to `kg`.

```yaml
mode: sidecar                 # sidecar | co_located
kg_database: ${KG_DSN}

sources:
  pagila:
    type: postgres
    dsn: ${PG_DSN}
    schemas: [public]
    exclude_tables: []
    statement_timeout_ms: 5000
  warehouse:
    type: mssql
    dsn: mssql://reader:${MSSQL_PASSWORD}@warehouse.example:1433/sales
    schemas: [dbo]
  contracts:
    type: s3
    bucket: acme-contracts
    prefix: ""
    region: eu-north-1
    acl:
      roles: [legal]

embeddings:
  provider: local             # local | openai | none
  model: joinhound-hash-v1
  dim: 1024
  base_url: null
  api_key: null

judge:
  provider: none              # none | openai
  base_url: null
  api_key: null
  model: null
  redact: false
  sensitive_columns: []

profiler:
  sample_values: 10000
  containment_threshold: 0.5
  auto_approve: null

engine:
  seeds_k: 10
  max_depth: 3
  beam_width: 20
  fanout: 25
  depth_decay: 0.8
  budget_tokens: 4000
  timeout_ms: 10000
  cache_ttl_seconds: 30

server:
  transport: stdio            # stdio | http
  http_port: 8787
  auth_token: null
```

## Fields

`mode` chooses the executor. `sidecar` searches a source and then reads the matched rows. `co_located` reads an exact or normalized match in one statement when that source can do the comparison itself. Fuzzy and semantic matches still use `kg.value_index`.

`kg_database` is the service database. Joinhound creates the `kg` schema there. It does not create schemas in a customer database.

A `postgres` source is read-only. `statement_timeout_ms` bounds one statement. `exclude_tables` is a list of table names to skip.

An `mssql` source is the same idea for SQL Server. The DSN is `mssql://user:password@host:port/database`. The login should have only read rights. Row addresses use `mssql://source/schema.table#pk=...`.

An `s3` source reads one bucket prefix. `acl.roles` is the set of roles allowed to see its passages. A caller who passes other roles does not receive those passages.

`embeddings.provider: local` is the hashed trigram embedder. `openai` calls an OpenAI-compatible `/embeddings` endpoint. `none` stores no vectors. Changing `model` or `dim` after a sync requires `joinhound sync --reindex`.

`judge.provider: none` keeps every proposal. `openai` asks a model about proposals whose confidence is in the middle of the range. `redact: true` replaces values of `sensitive_columns` with their shape before the prompt is built.

`engine.timeout_ms` stops a walk. `cache_ttl_seconds` is how long a `get_context` response may be reused. The cache holds the response, not pairs of records. Zero disables it.

`server.transport: http` requires `auth_token`. The listen address is `127.0.0.1` and the port is `http_port`. Put TLS in front of the process.

## Tracing

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP HTTP base URL, such as `http://127.0.0.1:4318`. The process then exports spans for `profile`, `sync`, `get_context`, and model calls. Leave it unset and nothing is exported.
