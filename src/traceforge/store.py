"""SQLite event store. Each episode has a tamper-evident ordered hash chain.

Hashes detect accidental/partial edits, not a database owner rewriting the whole chain.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .models import Json


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
          config TEXT NOT NULL, summary TEXT, manifest TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS episodes (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
          scenario_id TEXT NOT NULL, repetition INTEGER NOT NULL, seed INTEGER NOT NULL,
          status TEXT NOT NULL, result TEXT,
          UNIQUE(run_id, scenario_id, repetition)
        );
        CREATE TABLE IF NOT EXISTS events (
          episode_id TEXT NOT NULL REFERENCES episodes(id), seq INTEGER NOT NULL,
          timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
          prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
          PRIMARY KEY(episode_id, seq)
        );
        CREATE INDEX IF NOT EXISTS episodes_run ON episodes(run_id);
        """)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def create_run(self, run_id: str, config: Json, manifest: Json) -> None:
        with self.lock:
            self.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)",
                            (run_id, now(), "queued", canonical(config), None, canonical(manifest)))

    def update_run(self, run_id: str, status: str, summary: Json | None = None) -> None:
        with self.lock:
            self.db.execute("UPDATE runs SET status=?, summary=? WHERE id=?",
                            (status, canonical(summary) if summary is not None else None, run_id))

    def create_episode(self, episode_id: str, run_id: str, scenario: str, rep: int, seed: int) -> None:
        with self.lock:
            self.db.execute("INSERT INTO episodes VALUES(?,?,?,?,?,?,?)",
                            (episode_id, run_id, scenario, rep, seed, "running", None))

    def finish_episode(self, episode_id: str, result: Json) -> None:
        with self.lock:
            self.db.execute("UPDATE episodes SET status='completed',result=? WHERE id=?",
                            (canonical(result), episode_id))

    def append(self, episode_id: str, kind: str, payload: Json) -> Json:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                last = self.db.execute("SELECT seq,hash FROM events WHERE episode_id=? ORDER BY seq DESC LIMIT 1", (episode_id,)).fetchone()
                seq, prev = (last["seq"] + 1, last["hash"]) if last else (0, "0" * 64)
                event = {"episode_id": episode_id, "seq": seq, "timestamp": now(),
                         "kind": kind, "payload": payload, "prev_hash": prev}
                digest = hashlib.sha256(canonical(event).encode()).hexdigest()
                self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                                (episode_id, seq, event["timestamp"], kind, canonical(payload), prev, digest))
                self.db.execute("COMMIT")
                return {**event, "hash": digest}
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def events(self, episode_id: str, after: int = -1) -> list[Json]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM events WHERE episode_id=? AND seq>? ORDER BY seq", (episode_id, after)).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def verify(self, episode_id: str) -> Json:
        previous = "0" * 64
        events = self.events(episode_id)
        for seq, event in enumerate(events):
            body = {k: v for k, v in event.items() if k != "hash"}
            digest = hashlib.sha256(canonical(body).encode()).hexdigest()
            if event["seq"] != seq or event["prev_hash"] != previous or event["hash"] != digest:
                return {"valid": False, "events": len(events), "broken_at": seq}
            previous = digest
        # Final event anchors completion; tail truncation of a finished trace is detectable.
        episode = self.episode(episode_id)
        if episode and episode["status"] == "completed" and (not events or events[-1]["kind"] != "episode.completed"):
            return {"valid": False, "events": len(events), "broken_at": len(events)}
        return {"valid": True, "events": len(events), "head_hash": previous}

    def episode(self, episode_id: str) -> Json | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        return {**dict(row), "result": json.loads(row["result"]) if row["result"] else None} if row else None

    def episodes(self, run_id: str) -> list[Json]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM episodes WHERE run_id=? ORDER BY scenario_id,repetition", (run_id,)).fetchall()
        return [{**dict(r), "result": json.loads(r["result"]) if r["result"] else None} for r in rows]

    def run(self, run_id: str) -> Json | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return {**dict(row), **{k: json.loads(row[k]) if row[k] else None for k in ("config", "summary", "manifest")}}

    def runs(self, limit: int = 50) -> list[Json]:
        with self.lock:
            rows = self.db.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self.run(r["id"]) for r in rows]  # type: ignore[misc]

    def interrupt_unfinished(self) -> int:
        """No phantom 'running' runs after a process restart. Resume is explicit, not implied."""
        with self.lock:
            cursor = self.db.execute("UPDATE runs SET status='interrupted' WHERE status IN ('queued','running')")
            return cursor.rowcount
