"""SQLite-backed TTL cache for provider payloads.

Keeps live fetches cheap to repeat within a session and lets the demo
survive flaky networks: a payload fetched once is served from disk until
its TTL lapses, after which the bundle loader falls back to fixtures.
"""

from __future__ import annotations

import json
import sqlite3
import time


class DataCache:
    """Tiny (ticker, source) -> JSON payload cache with per-row TTL.

    Schema: cache(ticker, source, fetched_at, payload TEXT,
    PRIMARY KEY(ticker, source)). The TTL is stored inside the payload
    envelope so each row can carry its own expiry.
    """

    def __init__(self, path: str = ".delphi_cache.sqlite"):
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                ticker TEXT NOT NULL,
                source TEXT NOT NULL,
                fetched_at REAL NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (ticker, source)
            )
            """
        )
        self._conn.commit()

    def get(self, ticker: str, source: str) -> dict | None:
        """Return the cached payload, or None if missing/expired/corrupt."""
        try:
            row = self._conn.execute(
                "SELECT fetched_at, payload FROM cache WHERE ticker = ? AND source = ?",
                (ticker.upper(), source),
            ).fetchone()
            if row is None:
                return None
            fetched_at, raw = row
            envelope = json.loads(raw)
            ttl_hours = float(envelope.get("ttl_hours", 24))
            if time.time() - fetched_at > ttl_hours * 3600:
                return None
            data = envelope.get("data")
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def put(self, ticker: str, source: str, payload: dict, ttl_hours: float = 24) -> None:
        """Upsert a payload; silently no-ops on serialization/db errors."""
        try:
            raw = json.dumps({"ttl_hours": ttl_hours, "data": payload})
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (ticker, source, fetched_at, payload) "
                "VALUES (?, ?, ?, ?)",
                (ticker.upper(), source, time.time(), raw),
            )
            self._conn.commit()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
