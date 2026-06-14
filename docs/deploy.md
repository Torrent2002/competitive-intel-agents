# Deploying competitive-intel-agents

The project ships two supported install paths. Pick whichever matches
how you intend to run the dashboard.

## Option A — local virtualenv (development / single-user)

```bash
git clone git@github.com:Torrent2002/competitive-intel-agents.git
cd competitive-intel-agents
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .

# Configure a real model (optional — skip for fully fake pipeline)
cp config/model.example.json config/model.json
$EDITOR config/model.json   # fill in api_key, model, endpoint

competitive-intel web --workspace .competitive-intel --port 8080
```

Browse to `http://127.0.0.1:8080`.

## Option B — Docker Compose (recommended for "real" deployments)

```bash
git clone git@github.com:Torrent2002/competitive-intel-agents.git
cd competitive-intel-agents

# Optional: secrets and overrides. Never commit this file.
cat > .env <<'EOF'
CIA_API_TOKEN=<long-random-string>
CIA_MODEL_API_KEY=<your-anthropic-or-openai-key>
CIA_MODEL_PROVIDER=anthropic-compatible
CIA_MODEL_ENDPOINT=https://api.anthropic.com
CIA_MODEL_NAME=claude-sonnet-4-6
CIA_LOG_LEVEL=INFO
EOF

mkdir -p ./data
docker compose up -d
curl http://127.0.0.1:8080/health        # → {"status":"ok"}
curl http://127.0.0.1:8080/ready         # → {"status":"ready"}
```

The compose file mounts `./data` on the host into `/data` in the
container; that is where `artifacts.sqlite`, `journal.sqlite` and
`runs.json` live. Backups: copy `./data` while the container is stopped.

To stop:

```bash
docker compose down            # leaves ./data intact
docker compose down -v         # also removes the data volume
```

## Environment variables

| Variable                | Default       | Effect                                                                 |
|-------------------------|---------------|------------------------------------------------------------------------|
| `CIA_API_TOKEN`         | _(unset)_     | When set, every `/api/` request must carry `Authorization: Bearer <t>` |
| `CIA_LOG_LEVEL`         | `INFO`        | Log threshold (`DEBUG` / `INFO` / `WARNING` / `ERROR`)                 |
| `CIA_LOG_FORMAT`        | `text`        | `text` (human) or `json` (one JSON object per line). Image default = `json` |
| `CIA_LOG_FILE`          | _(stderr)_    | Redirect logs to a file path                                           |
| `CIA_MODEL_PROVIDER`    | `fake`        | `anthropic-compatible` / `openai-compatible` / `fake`                  |
| `CIA_MODEL_ENDPOINT`    | _(unset)_     | Provider URL                                                           |
| `CIA_MODEL_API_KEY`     | _(unset)_     | Provider key                                                           |
| `CIA_MODEL_NAME`        | _(unset)_     | Model identifier                                                       |
| `CIA_MAX_RUN_SECONDS`   | `600`         | Wall-clock cap per run; `0` disables the deadline                      |
| `SERPER_API_KEY`        | _(unset)_     | Serper.dev key — preferred over HTML search adapters when present      |

## External services accessed at runtime

The collector and model runtime reach out to:

- The model provider URL configured by `CIA_MODEL_ENDPOINT` (default
  Anthropic API).
- `https://google.serper.dev` when `SERPER_API_KEY` is set.
- `https://duckduckgo.com`, `https://www.bing.com`, `https://www.baidu.com`,
  `https://www.sogou.com` as fallbacks when Serper is missing or
  rate-limited.
- Arbitrary URLs returned by search results when `WebFetchTool` runs.

If your environment has restrictive egress, allow-list the model
provider plus Serper, and the rest is best-effort.

## Health endpoints

- `GET /health` — liveness. Returns 200 as long as the process is
  responsive. Used by `HEALTHCHECK` in the Dockerfile.
- `GET /ready` — readiness. Returns 200 only when the workspace is
  reachable; 503 with the underlying error when it is not. Wire this
  to a load-balancer probe so traffic stops while storage is degraded.

Both endpoints are reachable without the API token even when
`CIA_API_TOKEN` is set, because container orchestrators cannot easily
inject Bearer headers into their probes.

## Graceful shutdown

The web server traps `SIGTERM` and `SIGINT` and stops accepting new
connections, then exits when the in-flight HTTP requests finish. **It
does not wait for background `run` threads** spawned by `POST /api/runs`
or the dashboard form: those are daemon threads that die with the
process. If you need at-least-once run completion semantics, retry the
run with the same input after restart — the orchestrator is idempotent
on `run_id` collision.

## CI

`.github/workflows/ci.yaml` runs `pytest tests/unit -q -m "not
preexisting_fail"` on every PR and push to `main`. The
`preexisting_fail` marker is applied automatically by
`tests/conftest.py` for tests that were already failing on the branch
when CI was introduced. New regressions must be fixed at the source —
do not extend the marker list.

## Known limitations

- **Single instance only** — `artifacts.sqlite` and `journal.sqlite` use
  default SQLite locking, which is not safe across processes writing
  concurrently. To run more than one replica, swap to PostgreSQL
  (a planned P2 follow-up).
- **In-process rate limiting** — token buckets live in memory; multi-
  instance deployments will collectively exceed per-engine limits. The
  fix is a Redis-backed token bucket, also tracked as a follow-up.
- **No background-run completion guarantee** — a kill -9 / OOM during a
  long run loses the in-flight orchestrator state. The journal records
  whatever rounds finished before the kill.
