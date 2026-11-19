"""Build a self-contained recorded dashboard. No fake calls or fabricated results."""
from __future__ import annotations

import json
import base64
import gzip
from pathlib import Path

from .engine import replay
from .metrics import compare
from .scenarios import SCENARIOS
from .store import Store


def build_showcase(store: Store, output: Path) -> None:
    runs = [r for r in store.runs() if r["status"] == "completed"][:3]
    if not runs:
        raise ValueError("Run the demo first; no completed experiments to export")
    data = {"runs": [], "episodes": {}, "scenarios": [s.public() for s in SCENARIOS], "comparisons": {}}
    for run in runs:
        episodes = store.episodes(run["id"])
        data["runs"].append({**run, "episodes": episodes})
        for episode in episodes:
            data["episodes"][episode["id"]] = {**episode, "events": store.events(episode["id"]),
                                                    "integrity": store.verify(episode["id"]), "replay": replay(store, episode["id"])}
    for left in runs:
        for right in runs:
            try:
                data["comparisons"][left["id"]+":"+right["id"]] = compare(store.episodes(left["id"]), store.episodes(right["id"]))
            except ValueError:
                pass
    static = Path(__file__).parent / "static"
    html = (static/"index.html").read_text()
    html = html.replace('<link rel="stylesheet" href="/style.css">', '<style>'+(static/"style.css").read_text()+'</style>')
    html = html.replace('<script defer src="/app.js"></script>', '')
    icon = 'data:image/svg+xml;base64,' + base64.b64encode((static/'icon.svg').read_bytes()).decode()
    html = html.replace('/icon.svg', icon)
    html = html.replace('href="/"', 'href="#"').replace('href="/api/health"', 'href="https://github.com/Djordje3002/traceforge"')
    html = html.replace('LOCAL INSTANCE', 'RECORDED DEMO')
    encoded = base64.b64encode(gzip.compress(json.dumps(data, separators=(',', ':')).encode(), mtime=0)).decode()
    html = html.replace('</body>', '<script type="application/octet-stream" id="recorded-data" data-encoding="gzip">'+encoded+'</script><script>'+(static/'app.js').read_text()+'</script></body>')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
