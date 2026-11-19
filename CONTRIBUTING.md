# Contributing

Use Python 3.11 or newer. The application and test suite have no runtime dependencies.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m traceforge --db data/dev.db demo
```

Add a failure case before fixing an engine invariant. Prefer assertions about effects, call IDs, budgets, and persisted traces over tests that repeat implementation details. Never add a real payment or email backend to the default suite. Keep expected outcomes separate from agent observations. Include scenario hashes and complete configurations with published results.

Optional code checks use `pip install -e '.[dev]'`, `ruff check .`, and `coverage run --source=traceforge -m unittest discover -s tests`. The configured style is Ruff's Python 3.11 rules with a 100-character target. Network smoke tests are opt-in via `TRACEFORGE_NETWORK_TESTS=1` and enabled in CI.

The files `docs/demo.html`, `docs/scenarios.md`, and `examples/demo-results.json` are generated from actual runs/catalogs. Regenerate after intentional fixture changes and review behavioral changes in the JSON report. Do not hand-edit result percentages. The recorded HTML contains only fictional simulation data.

Optional browser checks use Node 22, `npm install`, `npx playwright install chromium`, and `npm run test:ui`. CI runs these against the live server and the recorded HTML, and uploads desktop/mobile/trace screenshots as evidence. Playwright is a development dependency only; it is not needed to run the Python application.
