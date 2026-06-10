"""DELPHI API — run lifecycle + SSE streaming of the debate."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agents.graph import has_live_mode, live_provider, registry
from ..data.bundle import available_tickers

app = FastAPI(title="DELPHI", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    ticker: str
    mode: str | None = None      # "live" | "simulation" | None → auto


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "live_mode_available": has_live_mode(),
            "live_provider": live_provider()}


@app.get("/api/tickers")
def tickers() -> list[dict]:
    return available_tickers()


@app.get("/api/search")
def search(q: str = "") -> list[dict]:
    """Universal company search: fixtures + every SEC registrant + European
    exchanges via Yahoo. Falls back to the fixture universe offline."""
    q = q.strip()
    featured = [{**t, "exchange": "", "country": "US", "source": "featured"}
                for t in available_tickers()]
    if len(q) < 2:
        return featured
    if os.environ.get("DELPHI_OFFLINE") == "1":
        qq = q.upper()
        return [t for t in featured
                if qq in t["ticker"] or qq in t["company"].upper()]
    try:
        from ..data.registry import search_companies
        return search_companies(q)
    except Exception:
        qq = q.upper()
        return [t for t in featured
                if qq in t["ticker"] or qq in t["company"].upper()]


@app.post("/api/runs")
async def create_run(req: RunRequest) -> dict:   # async: Run.start() needs the loop
    universe = {t["ticker"] for t in available_tickers()}
    ticker = req.ticker.upper().strip()
    if ticker not in universe:
        if os.environ.get("DELPHI_OFFLINE") == "1":
            raise HTTPException(
                404, detail=f"Offline mode covers {sorted(universe)} — unset DELPHI_OFFLINE for universal coverage")
        try:
            from ..data.registry import resolve
            info = await asyncio.to_thread(resolve, ticker)
        except Exception:
            info = None
        if not info:
            raise HTTPException(404, detail=f"No US/European listing found for “{req.ticker}”")
        ticker = info["ticker"]
    run = registry.create(ticker, req.mode)
    return {"run_id": run.id, "ticker": run.ticker, "mode": run.mode}


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    run = registry.get(run_id)
    if not run:
        raise HTTPException(404, detail="unknown run")
    return StreamingResponse(
        run.bus.stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/report")
def report(run_id: str) -> dict:
    run = registry.get(run_id)
    if not run:
        raise HTTPException(404, detail="unknown run")
    if not run.state.note:
        raise HTTPException(409, detail="note not yet published")
    return run.state.note.model_dump()


# Serve the production frontend build when present (dev uses Vite on :5173).
_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if _dist.exists():
    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        if catchall.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        file_path = _dist / catchall
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_dist / "index.html")
