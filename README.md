<p align="center"><img src="docs/cover.svg" alt="TraceForge — Agent Reliability Lab. Good answers are easy. Correct actions are harder." width="100%"></p>

<h1 align="center">TraceForge</h1>

<p align="center">A reliability lab for AI agents that act on the world.<br>Inject failures. Inspect decisions. Evaluate effects. Replay the evidence.</p>

<p align="center">
  <a href="https://github.com/Djordje3002/traceforge/actions/workflows/ci.yml"><img src="https://github.com/Djordje3002/traceforge/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11 or newer">
  <img src="https://img.shields.io/badge/runtime_dependencies-0-3C7857" alt="Zero runtime dependencies">
  <img src="https://img.shields.io/badge/scenarios-16-647C57" alt="16 scenarios">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-73846D" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#the-dashboard">Screenshots</a> ·
  <a href="#recorded-results">Results</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#evaluate-a-real-model">Real models</a> ·
  <a href="#documentation">Documentation</a>
</p>

---

## The problem

An agent says “refund complete.” The payment API actually failed.

Another agent retries after a timeout. The first request already committed, so the customer receives two refunds.

A third reads a document that claims to be an administrator and forwards customer information to an unauthorized address.

These failures happen between a model's intention and a system's effects. TraceForge makes that gap inspectable. It runs tool-using agents through an isolated customer-support simulation, injects dependency failures, checks capabilities before execution, and grades business state against an independent oracle.

Every episode leaves a persistent trace. Inspect the arguments, policy decisions, retries, receipts, and state changes that explain its outcome—then reconstruct the state and recompute the grade without calling the model again.

The offline path runs on the Python standard library. No API key, external database, agent framework, or frontend build is required.

## The dashboard

<p align="center"><img src="docs/screenshots/dashboard-desktop.png" alt="Dashboard showing 144 fixture episodes across three experiments, with separate task-success and safe-effects metrics" width="100%"></p>
<p align="center"><sub>Actual application screenshots from the Chromium CI checks. Overview metrics aggregate all three fixture configurations.</sub></p>

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>Follow the execution</h3>
      <img src="docs/screenshots/trace-inspector.png" alt="Trace inspector showing the lost-acknowledgement case, grading checks, and execution events" width="100%">
      <p>Inspect arguments, authorization decisions, retries, state snapshots, and an independently computed result.</p>
    </td>
    <td width="50%" valign="top">
      <h3>Measure a change</h3>
      <img src="docs/screenshots/comparison.png" alt="Paired comparison showing a 75-percentage-point fixture success difference with a bootstrap interval" width="100%">
      <p>Pair comparable episodes, surface regressions, and report uncertainty using scenario clusters.</p>
    </td>
  </tr>
</table>

<details>
<summary>See the mobile layout</summary>

<p align="center"><img src="docs/screenshots/dashboard-mobile.png" alt="Dashboard at a 390-pixel mobile viewport" width="320"></p>

</details>

[Download the recorded demo](https://github.com/Djordje3002/traceforge/raw/refs/heads/main/docs/demo.html) and open the downloaded HTML in a modern browser. It includes real fixture records and supports inspection, comparisons, and JSON export without a live API. New experiments require the Python app.

## Quick start

### Run from source

Use Python 3.11 or newer:

```bash
git clone https://github.com/Djordje3002/traceforge.git
cd traceforge

# Create naive, guarded naive, and guarded resilient experiments.
PYTHONPATH=src python3 -m traceforge demo

# Open the local dashboard server.
PYTHONPATH=src python3 -m traceforge serve
```

Open [http://127.0.0.1:8741](http://127.0.0.1:8741).

The demo creates 144 episodes: 16 scenarios × 3 repetitions × 3 configurations. Customers, refunds, messages, and tickets are simulated. No provider requests are made.

On macOS, check `python3 --version`; the system Python can be older than a separately installed Python. Substitute `python3.11` or another supported interpreter as needed. Source commands above use POSIX shell syntax.

### Install the CLI

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

traceforge demo
traceforge serve
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell, then use the installed `traceforge` commands. The installed CLI and `PYTHONPATH=src python3 -m traceforge` expose the same app.

### Your first investigation

1. Open the guarded resilient experiment.
2. Select “Committed, but unacknowledged,” the `lost-ack` scenario.
3. Expand the failed refund attempt, retry event, and successful receipt.
4. Inspect the snapshots: the retry must leave exactly one refund.
5. Choose “Verify & replay offline” to verify the trace and recompute its grade.
6. Compare the unguarded naive experiment with the guarded resilient experiment.

The [recorded report](examples/demo-results.json) and [evaluation notes](docs/evaluation.md) explain the numbers.

## What you can evaluate

| Question | Implemented mechanism |
|---|---|
| Did the task actually finish? | A separate grader inspects refund, notification, ticket, and customer-read state. |
| Did the agent stay within its authority? | Capabilities enforce customer/order scope, refund limits, allowed recipients, and duplicate-order protection. |
| What happens when a dependency fails? | Fixed schedules inject transient errors, timeouts, malformed responses, and lost acknowledgements. |
| Can a retry create another effect? | Write tools cache receipts by idempotency key and reject conflicting reuse. |
| Can invalid tool calls reach the world? | Contracts reject unknown tools, unexpected fields, invalid types, and out-of-range values. |
| Will an agent stop? | Step, tool-call, token, and time budgets bound execution. |
| Why did an episode fail? | Persisted events capture decisions, checks, errors, retries, receipts, and snapshots. |
| Can evidence be checked later? | Ordered SHA-256 chains and offline regrading expose incomplete edits or mismatched results. |
| Did a change help? | Paired comparisons identify improvements and regressions, with scenario-cluster bootstrap intervals. |

### The simulated tool surface

| Tool | Purpose | Effect |
|---|---|---|
| `search_docs` | Retrieve policy and potentially adversarial document content | Read |
| `get_customer` | Retrieve customer/order eligibility | Recorded customer read |
| `issue_refund` | Issue a refund in integer cents | Simulated ledger write |
| `send_message` | Notify the permitted recipient | Simulated message write |
| `create_ticket` | Escalate an unresolved request | Simulated ticket write |

Each episode owns an in-memory world. There is no shell tool, real email delivery, or real payment integration in the default suite.

## A failure worth understanding

The `lost-ack` case tests a common ambiguity: a request failed from the caller's perspective, while its effect succeeded in the target system.

```mermaid
sequenceDiagram
    participant E as Executor
    participant W as Simulated ledger
    participant F as Fault injector
    E->>W: Refund with key K
    W->>W: Commit refund and cache receipt
    W->>F: Original receipt
    F-->>E: Acknowledgement lost
    E->>W: Retry with the same key K
    W-->>E: Return the original receipt
```

The executor retries identical arguments. The ledger returns its cached receipt, preserving one effect. With enforcement enabled, a fresh-key attempt to refund the same order is blocked separately.

Idempotency handles repeated delivery of the same intent; the capability gate handles an additional intent that violates a business invariant. This guarantee applies to the simulated ledger. Real integrations need durable idempotency coordinated with the target transaction.

## Recorded results

Seed `42` · 16 scenarios · 3 repetitions · 48 episodes per configuration.

| Configuration | Task success | Safe effects | Enforced policy blocks |
|---|---:|---:|---:|
| Naive fixture, policy observed only | 25.00% | 56.25% | 0 |
| Naive fixture, policy enforced | 37.50% | 100.00% | 21 |
| Resilient fixture, policy enforced | 100.00% | 100.00% | 0 |

Blocking an unauthorized action can preserve safe effects while leaving the task unfinished. Completing a task requires the agent to recover, choose a valid action, or escalate correctly.

The naive-to-resilient comparison reports a `+75` percentage-point success difference, with a descriptive 95% scenario-cluster bootstrap interval of `+50` to `+93.75` points. Values come from the [committed report](examples/demo-results.json).

> These are hand-authored fixture results, not measurements of an LLM. Scripts intentionally know scenario identity and exercise selected failure paths. Repetitions test isolation and persistence; they do not create independent reasoning samples. This table establishes neither live-model performance nor general resistance to prompt injection.

Reproduce into a separate database and report:

```bash
PYTHONPATH=src python3 -m traceforge \
  --db data/reproduction.db demo \
  --repetitions 3 \
  --output data/reproduction.json
```

Selected scenario definitions are hashed into each run manifest. Episode seeds derive from the base seed, scenario ID, and repetition, independently of scheduling order. Run IDs, timestamps, and latency vary; fixture effects and grades remain reproducible for the same configuration and implementation.

### How comparisons work

The API requires the same scenario-suite hash and pairs completed episodes by scenario, repetition, and derived seed. It reports unmatched episodes explicitly. The comparison uses equally weighted per-scenario success differences and 2,000 seeded bootstrap draws over scenario clusters.

This avoids counting identical repetitions as independent tasks. Intervals describe this small suite and do not guarantee other-workflow performance. Aggregate Wilson intervals are also reported, with their dependence limitations explained in [evaluation.md](docs/evaluation.md).

## Scenario library

| Category | Cases | Scenario IDs |
|---|---|---|
| Correctness | Normal completion; valid but incorrect payment | `clean-refund`, `wrong-amount` |
| Resilience | Flaky reads; slow dependency; sustained outage | `transient-read`, `slow-tool`, `service-down` |
| Idempotency | Lost response after commit; repeated refund intent | `lost-ack`, `duplicate-intent` |
| Security | Exfiltration; forged authority; cross-tenant read; secret-marker disclosure | `injection-exfil`, `injection-refund`, `cross-tenant`, `message-injection` |
| Validation | Incorrect types; invented tool; malformed output | `bad-schema`, `unknown-tool`, `malformed-result` |
| Authorization | Request above the refund limit | `over-limit` |
| Efficiency | Repeated searches without progress | `runaway-loop` |

The [catalog](docs/scenarios.md) lists fault schedules. The [definitions](src/traceforge/scenarios.py) keep expected outcomes inspectable. The live model receives the task, capabilities, and observations; scenario IDs, grading oracles, and fault schedules are withheld from its conversation.

## Architecture

```mermaid
flowchart TD
    Entry["Dashboard, CLI, or HTTP client"] --> Runner["Bounded async runner"]
    Runner --> Agent["Script fixture or live model"]
    Agent --> Gate["Contracts, capabilities, budgets"]
    Gate --> World["Isolated world and fault schedules"]
    World --> Agent
    Runner --> Events["SQLite event store"]
    World --> Grader["Independent effect grader"]
    Events --> Replay["Verify and regrade offline"]
    Grader --> Compare["Paired statistical comparison"]
```

Each episode owns a world, agent instance, conversation, retry RNG, and counters. A semaphore bounds episode concurrency. Tools execute serially within an episode so authorization and mutation cannot race.

### Engineering choices

| Choice | Benefit | Tradeoff |
|---|---|---|
| Standard-library runtime | Easy to run, inspect, and reproduce | A small HTTP layer and explicit schema subset are maintained here. |
| SQLite with WAL | Inspect experiments after the process exits | Single-process ownership; small synchronous writes share the event loop. |
| Independent state oracle | A success claim cannot replace a business effect | Workflow-specific checks; limited semantic answer grading |
| Fixed faults and seeded jitter | Stable cases under different episode concurrency | No generated adversarial distribution or provider determinism claim |
| Snapshot-based replay | Reconstruct and regrade without executing tools | Extra storage; not computational replay of tool internals |
| Capabilities outside the model | Retrieved text cannot grant new authority | Depends on explicitly modeled invariants |

### Trace integrity and lifecycle

Events contain an episode ID, sequence, timestamp, kind, payload, previous hash, and hash. Reading the predecessor and appending an event happen in one transaction. Verification checks ordering, hash continuity, and a completed episode's terminal marker.

Replay reconstructs the last snapshot, recomputes the grade, and compares it with the terminal event and stored result. An attacker who rewrites the whole database and chain remains outside that integrity guarantee; externally anchored signatures are not implemented.

Runs can complete, fail, be cancelled, or become interrupted. Startup marks unfinished runs interrupted rather than silently resuming. Business state and receipts are in memory; the event database is not a durable payment ledger.

See [architecture.md](docs/architecture.md) for invocation order, cancellation, and boundaries.

## Evaluate a real model

The `openai-compatible` adapter implements a tool-calling conversation over a Chat Completions endpoint. It preserves call IDs, returns structured observations, and requires provider-reported usage.

```bash
export TRACEFORGE_BASE_URL="https://api.openai.com/v1"
export TRACEFORGE_MODEL="your-tool-capable-model-id"
export TRACEFORGE_API_KEY="your-api-key"

PYTHONPATH=src python3 -m traceforge run --config examples/live-model.json
```

The included configuration starts with four cases, one repetition, and concurrency `1`: `clean-refund`, `lost-ack`, `injection-exfil`, and `over-limit`.

| Variable | Purpose | Default |
|---|---|---|
| `TRACEFORGE_BASE_URL` | Base URL, without `/chat/completions` | `https://api.openai.com/v1` |
| `TRACEFORGE_MODEL` | Tool-capable model identifier | Required for live mode |
| `TRACEFORGE_API_KEY` | Provider credential | Required for live mode |

The endpoint must support `max_completion_tokens`, strict function-tool schemas, and `usage.prompt_tokens` / `usage.completion_tokens`. Compatible local servers can use HTTP loopback URLs; remote URLs must use HTTPS. Compatibility depends on the provider's implementation.

Credentials come from the server environment, not the browser form. Live evaluation incurs provider charges. Usage is checked after a response arrives, so a response can exceed the remaining cumulative token budget before its usage is known. This is not a hard dollar-spend cap.

The repository includes mocked protocol tests and scripted results, with no measured live-model results.

## Configure an experiment

```bash
PYTHONPATH=src python3 -m traceforge run --config examples/strict.json
```

<details>
<summary>Example: isolate a failure case</summary>

Save this as `data/lost-ack.json`, then pass it to `run --config`:

```json
{
  "agent": "scripted-resilient",
  "scenarios": ["lost-ack"],
  "repetitions": 3,
  "concurrency": 1,
  "seed": 42,
  "guardrails": true,
  "max_steps": 12,
  "max_tool_calls": 16,
  "max_tokens": 12000,
  "episode_timeout_s": 30,
  "tool_timeout_s": 0.05,
  "max_retries": 2
}
```

</details>

| Field | Default | Behavior |
|---|---|---|
| `agent` | `scripted-resilient` | Also accepts `scripted-naive` or `openai-compatible`. |
| `scenarios` | `[]` | Empty selects all; unknown or duplicate IDs fail. |
| `repetitions` | `3` | 1–30 repetitions per scenario |
| `concurrency` | `4` | 1–16 concurrent episodes |
| `seed` | `42` | Base for episode seeds and retry jitter |
| `guardrails` | `true` | Enforce policy; `false` observes without blocking. |
| `max_steps` | `12` | Agent decisions, 1–50 |
| `max_tool_calls` | `16` | Known, schema-valid attempts, including retries and denials |
| `max_tokens` | `12000` | Cumulative reported tokens; fixtures use zero. |
| `episode_timeout_s` | `30` | Episode deadline in seconds |
| `tool_timeout_s` | `0.5` | Per-attempt deadline in seconds |
| `max_retries` | `2` | Additional retryable-failure attempts, 0–5 |

Unknown fields fail validation. Invalid arguments and unknown tools are rejected before execution and remain bounded by decision steps. Exact bounds live in [models.py](src/traceforge/models.py).

The `demo` command sets a shorter tool timeout. This table describes `RunConfig` defaults, which can differ from examples and dashboard inputs.

## CLI reference

After installation, use `traceforge`; source users can substitute `PYTHONPATH=src python3 -m traceforge`.

```bash
# Run one experiment or a policy ablation.
traceforge run --config examples/strict.json
traceforge run --agent scripted-naive --no-guardrails --repetitions 3

# --db is a global option before the subcommand.
traceforge --db data/another.db demo --output data/another-report.json

# Inspect evidence without a model call.
traceforge replay EPISODE_ID
traceforge export RUN_ID data/run-bundle.json

# Export the three latest completed runs into one recorded dashboard.
traceforge showcase --output data/recorded-demo.html

traceforge serve --port 8742
traceforge --help
```

The default database, `data/traceforge.db`, is relative to the working directory. Use the same directory or an explicit `--db` when switching between CLI and dashboard. Run/episode IDs are in the dashboard and API. Showcase export requires completed runs.

## HTTP API

The server binds to loopback. JSON mutations require `Content-Type: application/json`.

```bash
curl http://127.0.0.1:8741/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"agent":"scripted-resilient","scenarios":["lost-ack"],"repetitions":3}'
```

| Operation | Route |
|---|---|
| Health and provider status | `GET /api/health` |
| Scenario catalog | `GET /api/scenarios` |
| List / launch experiments | `GET /api/runs` · `POST /api/runs` |
| Inspect / export | `GET /api/runs/{id}` · `GET /api/runs/{id}/export` |
| Cancel | `POST /api/runs/{id}/cancel` |
| Inspect / regrade episode | `GET /api/episodes/{id}` · `GET /api/episodes/{id}/replay` |
| Stream events | `GET /api/episodes/{id}/events` |
| Compare experiments | `POST /api/compare` |

SSE supports resumption with `Last-Event-ID` or `?after=seq`. Bundles use `traceforge.bundle.v1`. See [api.md](docs/api.md) for examples and stream behavior.

## Verification

CI runs 33 Python tests on Python 3.11, 3.12, and 3.13, including the opt-in socket test. A separate Chromium job checks the live app, recorded HTML, and mobile width. [Browse the workflow history](https://github.com/Djordje3002/traceforge/actions/workflows/ci.yml).

### Python checks

```bash
# No third-party test packages or network access needed.
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Include the loopback HTTP server test, as CI does.
TRACEFORGE_NETWORK_TESTS=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests -v
```

The default command skips the socket test. Checks cover lost acknowledgements, conflicting keys, policy scope, budgets, cancellation, concurrency-independent effects, corrupt/truncated traces, edited results, restart handling, provider contracts, HTTP validation, SSE, and export/replay.

### Browser checks

Node 22 and optional development dependencies are needed only for browser checks:

```bash
npm install
npx playwright install --with-deps chromium
npm run test:ui
```

The check launches local servers, creates experiments, filters scenarios, compares outcomes, verifies traces, checks exports, submits the form, checks mobile width, and opens the recorded demo without a live API. CI uploads screenshots; representative captures are in [docs/screenshots](docs/screenshots).

## Extend TraceForge

### Add scenarios and tools

Add a `Scenario` in [scenarios.py](src/traceforge/scenarios.py) with a task, capabilities, expected outcome, and optional `Fault` schedule. Keep grading expectations separate from agent observations. Add a regression assertion about effects or invariants, then regenerate intentionally changed reports.

Tools are defined through `ToolSpec`, `World`, and the policy in [tools.py](src/traceforge/tools.py). Contracts use an explicit JSON Schema subset; unsupported keywords fail closed.

### Integrate another agent

Implement the asynchronous `Agent` protocol in [agents.py](src/traceforge/agents.py): `decide(messages, remaining_tokens)` returns a `Decision`; `close()` releases resources.

A decision contains tool actions or a final answer and token usage. Register an adapter in `make_agent`, extend accepted `RunConfig.agent` values, and update CLI/dashboard choices when exposing it there. The engine's `agent_override` also supports episode-level integration tests.

### Use the Python API

```python
import asyncio

from traceforge.engine import Engine
from traceforge.models import RunConfig
from traceforge.store import Store


async def main():
    store = Store(":memory:")
    try:
        run_id = await Engine(store).run(
            RunConfig(scenarios=["lost-ack"], repetitions=1)
        )
        run = store.run(run_id)
        print(run["summary"]["success_rate"])
    finally:
        store.close()


asyncio.run(main())
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before changing effects or grading.

## Project map

| Path | Responsibility |
|---|---|
| [engine.py](src/traceforge/engine.py) | Execution, budgets, retries, cancellation, replay |
| [agents.py](src/traceforge/agents.py) | Protocol, fixtures, HTTP model adapter |
| [tools.py](src/traceforge/tools.py) | Contracts, policy, idempotency, world |
| [scenarios.py](src/traceforge/scenarios.py) | Cases and fault schedules |
| [metrics.py](src/traceforge/metrics.py) | Grading, summaries, paired comparisons |
| [store.py](src/traceforge/store.py) | SQLite persistence and chain verification |
| [server.py](src/traceforge/server.py) | Local JSON/SSE API and assets |
| [static/](src/traceforge/static) | Dashboard HTML, CSS, JavaScript |
| [showcase.py](src/traceforge/showcase.py) | Recorded-dashboard export |
| [tests/](tests) | Python system tests and Chromium checks |
| [examples/](examples) | Configurations and recorded report |

## Scope and boundaries

TraceForge v0.1.0 is a local engineering tool for an explicit simulated workflow. Its strengths are inspectable execution boundaries and reproducible failure cases.

- Safety grades cover enumerated state invariants. The secret-marker rule is a demonstration, and answer semantics are lightly checked.
- The server has no user authentication or hosted multi-user controls. Keep it on loopback rather than exposing it publicly.
- Event chains detect incomplete edits; they do not authenticate against an attacker rewriting the database and chain together.
- Business state and cached receipts do not survive a crash. External tools need their own durable effect guarantees.
- A thread-backed provider request can continue until its timeout after cancellation. Cancellation cannot retract a sent request.
- Traces contain generated content and arguments. Review custom scenarios and exports before sharing.

Full assumptions appear in [security.md](docs/security.md) and [architecture.md](docs/architecture.md).

## Future directions

Possible next steps, not included features:

- An independently authored, held-out suite.
- Structured terminal outcomes and stronger answer/effect consistency grading.
- More runtime adapters and measured live-model comparisons.
- Durable external-sandbox tools with explicit grants.
- Externally anchored signatures and resumable execution.

## Documentation

| Guide | What it explains |
|---|---|
| [Architecture](docs/architecture.md) | Boundaries, invocation order, transactions, lifecycle, tradeoffs |
| [Evaluation methodology](docs/evaluation.md) | Scoring, pairing, dependence, uncertainty, reproducibility |
| [Scenario catalog](docs/scenarios.md) | Cases and injected faults |
| [HTTP API](docs/api.md) | Routes, JSON, SSE, bundle format |
| [Security model](docs/security.md) | Trusted components, untrusted inputs, limitations |
| [Contributing](CONTRIBUTING.md) | Development commands and expectations |

## Contributing and license

Issues and focused improvements are welcome. Include a reproducible case, configuration, and expected versus observed effects. Never attach credentials or private customer traces to public issues.

TraceForge is licensed under the [MIT License](LICENSE).

<p align="center"><sub>Built for agents that act on the world—and the engineers responsible for what happens next.</sub></p>
