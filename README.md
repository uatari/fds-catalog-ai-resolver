# FDS Catalog AI Resolver

Async Python resolver service that uses `mcp-fds-product-catalog` for deterministic product lookup and BOM retrieval.

It is designed for:

- Vercel-safe async request intake
- live call helper flows
- quote-building assistants
- duplicate-check and fuzzy catalog resolution

## Runtime

Required:

- `OPENAI_API_KEY`

Optional:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL` default `gpt-4.1-mini`
- `SQLITE_PATH` default `./state/jobs.sqlite3`
- `REQUEST_TIMEOUT_MS` default `120000`
- `WORKER_POLL_INTERVAL_MS` default `1200`
- `RUN_WORKER` default `true`
- `API_HOST` default `0.0.0.0`
- `API_PORT` default `8011`
- `CATALOG_MCP_COMMAND` default `node`
- `CATALOG_MCP_ARGS` default sibling `mcp-fds-product-catalog/src/index.js`
- `CATALOG_MCP_CWD` default sibling `mcp-fds-product-catalog`

Local convenience:

- if this service has no local relay env, it will also try sibling `mcp-grist-ops-mcp/.env` for `N8N_GRIST_RELAY_*`

## Install

```bash
cd /Users/dimi3/workflows/fds-catalog-ai-resolver
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Run

```bash
cd /Users/dimi3/workflows/fds-catalog-ai-resolver
. .venv/bin/activate
python -m fds_catalog_ai_resolver serve
```

## API

- `POST /jobs/resolve`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/events`
- `POST /jobs/{job_id}/retry`
- `GET /jobs`
- `GET /health`

`POST /jobs/resolve` body:

```json
{
  "query": "White Vinyl Privacy Fence 5'H x 6'W",
  "family_name": "vinyl-fence",
  "unit_name": "Panel",
  "conversation": [
    {"role": "user", "text": "Need matching panel"}
  ],
  "metadata": {
    "source": "live-call-helper"
  }
}
```

The worker writes:

- job status in SQLite
- tool-call and decision events in SQLite
- final structured result JSON in SQLite
