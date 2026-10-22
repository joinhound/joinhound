# Quick start

This path connects the Pagila sample database and answers one question. A person who has Docker and Python 3.12 can finish it in a few minutes. The passwords below are the local development stack only.

## 1. Start the databases

```console
docker compose up --wait
scripts/load_pagila.sh
```

`kg-postgres` listens on port 55432. Pagila listens on port 55433. MinIO listens on port 59000. Jaeger listens on port 16686.

## 2. Install the command

```console
uv sync
```

`joinhound` and `jh` are the same command.

## 3. Write the configuration

Save this as `joinhound.yaml` in the repository root. It is local configuration. Do not commit it.

```yaml
mode: sidecar
kg_database: postgresql://joinhound:joinhound@localhost:55432/joinhound

sources:
  pagila:
    type: postgres
    dsn: postgresql://postgres:postgres@localhost:55433/pagila
    schemas: [public]
    statement_timeout_ms: 5000

embeddings:
  provider: local
  model: joinhound-hash-v1
  dim: 1024

judge:
  provider: none

engine:
  timeout_ms: 10000
  cache_ttl_seconds: 30

server:
  transport: stdio
```

`provider: local` hashes character trigrams. It does not download a model. Set `judge.provider` to `openai` only when you have an endpoint and a key. See [config.md](config.md).

## 4. Build the model and the index

```console
uv run joinhound init --config joinhound.yaml
uv run joinhound profile --config joinhound.yaml
uv run joinhound export ossie --out model.yaml --config joinhound.yaml
uv run joinhound sync --config joinhound.yaml
```

`init` creates the `kg` schema. `profile` reads the Pagila catalog and proposes column relationships. `export` writes an Ossie model. `sync` copies values only for approved fuzzy or semantic relationships.

Open `model.yaml`. Approved equality relationships are ordinary Ossie `relationships`. Everything else is under `custom_extensions` with `vendor_name: JOINHOUND`. Change a link's `status` to `approved` or `rejected`, then import the file:

```console
uv run joinhound import ossie model.yaml --config joinhound.yaml
```

## 5. Ask from an agent

```console
uv run joinhound serve --config joinhound.yaml
```

Point Cursor or Claude Desktop at that command:

```json
{
  "mcpServers": {
    "joinhound": {
      "command": "uv",
      "args": ["run", "joinhound", "serve", "--config", "/absolute/path/joinhound.yaml"]
    }
  }
}
```

The agent should call `get_context` first. A useful first question is a film title that appears in Pagila, such as "Who is in Academy Dinosaur?". If the response has `truncated: true`, the agent calls `expand` with the node URIs, not the node ids.

For a container, set `server.transport` to `http` and set `server.auth_token`. A request without `Authorization: Bearer <token>` is rejected.

To see a trace, start Jaeger with the compose file and export spans:

```console
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 uv run joinhound serve --config joinhound.yaml
```

Open `http://127.0.0.1:16686` and look for the service `joinhound`.
