# Local API

Base URL: `http://127.0.0.1:8741`. Mutation requests require `Content-Type: application/json`. The application is local-only. No cross-origin browser access is permitted.

| Method | Route | Result |
|---|---|---|
| GET | `/api/health` | Version and whether provider configuration is present |
| GET | `/api/scenarios` | Public catalog; does not include grading oracles |
| GET | `/api/runs` | Latest 50 experiments |
| POST | `/api/runs` | Validate config, launch experiment, return `202 {id}` |
| GET | `/api/runs/{id}` | Manifest, config, summary, episodes |
| POST | `/api/runs/{id}/cancel` | Request cancellation and await finalization |
| GET | `/api/runs/{id}/export` | Full JSON bundle with event traces |
| GET | `/api/episodes/{id}` | Result, events, chain integrity |
| GET | `/api/episodes/{id}/events` | SSE event stream; supports `Last-Event-ID` or `?after=seq` |
| GET | `/api/episodes/{id}/replay` | Verify trace, reconstruct state, recompute grade |
| POST | `/api/compare` | Paired scenario-cluster comparison |

```bash
curl http://127.0.0.1:8741/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"agent":"scripted-resilient","repetitions":3,"seed":42,"guardrails":true}'

curl http://127.0.0.1:8741/api/compare \
  -H 'Content-Type: application/json' \
  -d '{"left":"BASELINE_RUN_ID","right":"CANDIDATE_RUN_ID"}'

curl -N http://127.0.0.1:8741/api/episodes/EPISODE_ID/events
```

Config fields and bounds live in `RunConfig` in `models.py`. Unknown fields are rejected. Empty `scenarios` selects the whole suite; duplicate or unknown IDs fail. At most four runs may execute at once through the HTTP runtime. `max_tool_calls` counts known, schema-valid execution attempts (including denials and retries); malformed/unknown calls are still bounded by agent steps.

SSE emits named `trace` events with sequence IDs, then `done` after episode completion. A connection lasts at most 60 seconds; reconnect using its last sequence ID. Completed episodes stream their persisted history. The dashboard polls run-level progress and uses SSE for an active episode. Interrupted episodes can lack a terminal event after a process crash; interrupted runs are visibly marked at restart.

Export format is `traceforge.bundle.v1`: a run object and an array of episodes with event lists. Bundles contain full generated content, so review them before public sharing. The current CLI exports bundles but does not import them into a live database.
