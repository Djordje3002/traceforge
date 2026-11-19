from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .engine import Engine, replay
from .metrics import compare
from .models import RunConfig
from .server import serve
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="traceforge", description="Agent Reliability Lab")
    parser.add_argument("--db", default="data/traceforge.db")
    sub = parser.add_subparsers(dest="command", required=True)
    web = sub.add_parser("serve", help="Open the local dashboard server")
    web.add_argument("--port", type=int, default=8741)
    demo = sub.add_parser("demo", help="Run three offline fixture experiments")
    demo.add_argument("--repetitions", type=int, default=3)
    demo.add_argument("--output", default="examples/demo-results.json")
    run = sub.add_parser("run", help="Run an experiment")
    run.add_argument("--config", type=Path)
    run.add_argument("--agent", choices=["scripted-naive", "scripted-resilient", "openai-compatible"], default="scripted-resilient")
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--no-guardrails", action="store_true")
    check = sub.add_parser("replay", help="Verify and regrade a stored episode without a model")
    check.add_argument("episode_id")
    export = sub.add_parser("export", help="Export a run and all event traces")
    export.add_argument("run_id")
    export.add_argument("output", type=Path)
    showcase = sub.add_parser("showcase", help="Export a self-contained recorded dashboard")
    showcase.add_argument("--output", type=Path, default=Path("docs/demo.html"))
    args = parser.parse_args()
    if args.command == "serve":
        return serve(args.db, args.port)
    store = Store(args.db)
    engine = Engine(store)

    async def work():
        if args.command == "demo":
            ids = []
            for agent, guards in [("scripted-naive", False), ("scripted-naive", True), ("scripted-resilient", True)]:
                run_id = await engine.run(RunConfig(agent=agent, guardrails=guards, repetitions=args.repetitions, tool_timeout_s=0.02))
                ids.append(run_id)
                result = store.run(run_id)
                print(f"{run_id}  {agent:20} guards={str(guards):5}  success={result['summary']['success_rate']:.1%}  safe={result['summary']['safe_rate']:.1%}")
            report = {"kind": "scripted-fixture-demo", "notice": "Hand-authored scripts; these results are not measurements of any LLM.",
                      "runs": [store.run(i) for i in ids],
                      "comparison": compare(store.episodes(ids[0]), store.episodes(ids[2]))}
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        elif args.command == "run":
            config = RunConfig.from_dict(json.loads(args.config.read_text())) if args.config else RunConfig(agent=args.agent, repetitions=args.repetitions, guardrails=not args.no_guardrails)
            run_id = await engine.run(config)
            print(json.dumps(store.run(run_id), indent=2))
        elif args.command == "replay":
            result = replay(store, args.episode_id)
            print(json.dumps(result, indent=2))
            if not result["matches"]:
                raise SystemExit(1)
        elif args.command == "export":
            run = store.run(args.run_id)
            if not run:
                raise SystemExit("Run not found")
            bundle = {"format": "traceforge.bundle.v1", "run": run,
                      "episodes": [{**e, "events": store.events(e["id"])} for e in store.episodes(args.run_id)]}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(bundle, indent=2) + "\n")
            print(args.output)
        elif args.command == "showcase":
            from .showcase import build_showcase
            build_showcase(store, args.output)
            print(args.output)
    try:
        asyncio.run(work())
    finally:
        store.close()


if __name__ == "__main__":
    main()
