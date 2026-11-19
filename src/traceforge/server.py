"""Local HTTP + SSE application, using only the Python standard library.

The server binds loopback. It is a developer tool, not a public multi-tenant service.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import mimetypes
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .engine import Engine, replay
from .metrics import compare
from .models import RunConfig
from .scenarios import SCENARIOS, select_scenarios
from .store import Store, canonical

STATIC = Path(__file__).parent / "static"
IDENTIFIER = re.compile(r"^[a-f0-9]{16}$")


class Runtime:
    def __init__(self, db: str):
        self.store = Store(db)
        self.store.interrupt_unfinished()
        self.engine = Engine(self.store)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=10)

    async def launch(self, config: RunConfig) -> str:
        if len(self.engine.tasks) >= 4:
            raise ValueError("At most four simultaneous runs are allowed")
        return self.engine.launch(config)

    def close(self) -> None:
        async def stop():
            for run_id in list(self.engine.tasks):
                await self.engine.cancel(run_id)
        self.submit(stop())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()
        self.store.close()


def handler_for(runtime: Runtime):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TraceForge/" + __version__
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            # No request bodies, query strings, model secrets, or customer content in console logs.
            pass

        def _headers(self, status: int, content_type: str, length: int | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()

        def _json(self, status: int, value):
            data = canonical(value).encode()
            self._headers(status, "application/json; charset=utf-8", len(data))
            self.wfile.write(data)

        def _safe_request(self) -> bool:
            host = self.headers.get("Host", "")
            hostname = urlparse("http://" + host).hostname
            if hostname not in ("localhost", "127.0.0.1", "::1"):
                self._json(403, {"error": "Only loopback hosts are accepted"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + host:
                self._json(403, {"error": "Cross-origin requests are not allowed"})
                return False
            return True

        def do_GET(self):
            try:
                if not self._safe_request():
                    return
                self._get()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (ValueError, TypeError):
                self._json(400, {"error": "Invalid request"})

        def _get(self):
            parsed = urlparse(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            store = runtime.store
            if path == "/api/health":
                return self._json(200, {"status": "ok", "version": __version__, "mode": "local", "model_configured": bool(os.getenv('TRACEFORGE_MODEL') and os.getenv('TRACEFORGE_API_KEY'))})
            if path == "/api/scenarios":
                return self._json(200, [s.public() for s in SCENARIOS])
            if path == "/api/runs":
                return self._json(200, store.runs())
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
                run = store.run(parts[2])
                if not run:
                    return self._json(404, {"error": "Run not found"})
                if len(parts) == 3:
                    return self._json(200, {**run, "episodes": store.episodes(parts[2])})
                if len(parts) == 4 and parts[3] == "export":
                    episodes = store.episodes(parts[2])
                    return self._json(200, {"format": "traceforge.bundle.v1", "run": run,
                                           "episodes": [{**e, "events": store.events(e["id"])} for e in episodes]})
            if len(parts) >= 3 and parts[:2] == ["api", "episodes"]:
                episode = store.episode(parts[2])
                if not episode:
                    return self._json(404, {"error": "Episode not found"})
                if len(parts) == 3:
                    return self._json(200, {**episode, "events": store.events(parts[2]), "integrity": store.verify(parts[2])})
                if len(parts) == 4 and parts[3] == "replay":
                    return self._json(200, replay(store, parts[2]))
                if len(parts) == 4 and parts[3] == "events":
                    return self._stream(parts[2], int(self.headers.get("Last-Event-ID", query.get("after", ["-1"])[0])))
            assets = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/icon.svg": "icon.svg"}
            if path in assets:
                file = STATIC / assets[path]
                data = file.read_bytes()
                self._headers(200, (mimetypes.guess_type(file.name)[0] or "application/octet-stream") + "; charset=utf-8", len(data))
                return self.wfile.write(data)
            self._json(404, {"error": "Not found"})

        def _stream(self, episode_id: str, after: int):
            self._headers(200, "text/event-stream; charset=utf-8")
            self.close_connection = True
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                for event in runtime.store.events(episode_id, after):
                    self.wfile.write(f"id: {event['seq']}\nevent: trace\ndata: {canonical(event)}\n\n".encode())
                    after = event["seq"]
                self.wfile.flush()
                episode = runtime.store.episode(episode_id)
                if episode and episode["status"] == "completed":
                    self.wfile.write(b"event: done\ndata: {}\n\n")
                    self.wfile.flush()
                    return
                time.sleep(0.1)

        def do_POST(self):
            try:
                if not self._safe_request():
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self._json(415, {"error": "Use application/json"})
                if self.headers.get("Transfer-Encoding"):
                    return self._json(400, {"error": "Chunked request bodies are unsupported"})
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    return self._json(413, {"error": "Body must be 1..65536 bytes"})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Body must be an object")
                path = urlparse(self.path).path
                if path == "/api/runs":
                    config = RunConfig.from_dict(data)
                    select_scenarios(config.scenarios)
                    return self._json(202, {"id": runtime.submit(runtime.launch(config))})
                if path == "/api/compare":
                    if any(not isinstance(data.get(side),str) or not IDENTIFIER.fullmatch(data[side]) for side in ('left','right')):
                        raise ValueError("left and right must be run IDs")
                    left, right = runtime.store.run(data.get("left", "")), runtime.store.run(data.get("right", ""))
                    if not left or not right:
                        return self._json(404, {"error": "Both runs must exist"})
                    if left["manifest"]["suite_sha256"] != right["manifest"]["suite_sha256"]:
                        raise ValueError("Runs must use the same scenario suite")
                    return self._json(200, compare(runtime.store.episodes(left["id"]), runtime.store.episodes(right["id"])))
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
                    return self._json(200, {"cancelled": runtime.submit(runtime.engine.cancel(parts[2]))})
                return self._json(404, {"error": "Not found"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)[:500]})
            except concurrent.futures.TimeoutError:
                self._json(503, {"error": "Runtime busy"})
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


def serve(db: str, port: int = 8741) -> None:
    runtime = Runtime(db)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(runtime))
    except OSError:
        runtime.close()
        raise
    server.daemon_threads = True
    print(f"TraceForge → http://127.0.0.1:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.close()
