"""Typed event stream — the wire protocol between the debate graph and the UI.

Every event is one SSE message: `event: <type>` + `data: <json>`.
The frontend mirrors these in src/lib/types.ts. Keep the two in lockstep.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

from .state import (
    AgentId,
    AuditCheck,
    Citation,
    Claim,
    ConvictionBreakdown,
    FootballFieldBar,
    GeoExposure,
    KeyNumber,
    MarketSnapshot,
    MonteCarloSummary,
    Objection,
    Phase,
    Rating,
    Rebuttal,
    ResearchNote,
    ScenarioCell,
    Thesis,
    Verdict,
)


class EventBus:
    """Async fan-out queue. The graph publishes; SSE subscribers consume."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self.history: list[dict[str, Any]] = []
        self._closed = False

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for ev in self.history:        # replay so late joiners see the full run
            q.put_nowait(ev)
        if self._closed:
            q.put_nowait(None)
        else:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def emit(self, type_: str, data: dict[str, Any]) -> None:
        ev = {"type": type_, "data": data}
        self.history.append(ev)
        for q in list(self._subscribers):
            q.put_nowait(ev)

    def close(self) -> None:
        self._closed = True
        for q in list(self._subscribers):
            q.put_nowait(None)

    async def stream(self) -> AsyncIterator[str]:
        q = self.subscribe()
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                yield f"event: {ev['type']}\ndata: {json.dumps(ev['data'])}\n\n"
        finally:
            self.unsubscribe(q)


class Emitter:
    """Typed helpers so graph code never hand-writes event dicts."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    def run_started(self, run_id: str, ticker: str, company: str, mode: str) -> None:
        self.bus.emit("run_started", {"run_id": run_id, "ticker": ticker, "company": company, "mode": mode})

    def phase_changed(self, phase: Phase, detail: str = "") -> None:
        self.bus.emit("phase_changed", {"phase": phase.value, "detail": detail})

    def plan_ready(self, items: list[str]) -> None:
        self.bus.emit("plan_ready", {"items": items})

    def agent_status(self, agent: AgentId, status: str) -> None:
        # status: idle | reading | thinking | speaking | rebutting | done
        self.bus.emit("agent_status", {"agent": agent.value, "status": status})

    def message_start(self, agent: AgentId, message_id: str, kind: str = "finding") -> None:
        self.bus.emit("message_start", {"agent": agent.value, "id": message_id, "kind": kind})

    def message_delta(self, message_id: str, text: str) -> None:
        self.bus.emit("message_delta", {"id": message_id, "text": text})

    def message_end(self, message_id: str) -> None:
        self.bus.emit("message_end", {"id": message_id})

    def tool_call(self, agent: AgentId, call_id: str, tool: str, args: str) -> None:
        self.bus.emit("tool_call", {"agent": agent.value, "id": call_id, "tool": tool, "args": args})

    def tool_result(self, call_id: str, summary: str) -> None:
        self.bus.emit("tool_result", {"id": call_id, "summary": summary})

    def market_snapshot(self, snap: MarketSnapshot) -> None:
        self.bus.emit("market_snapshot", snap.model_dump())

    def citation_added(self, citation: Citation) -> None:
        self.bus.emit("citation_added", citation.model_dump())

    def claim_filed(self, claim: Claim) -> None:
        self.bus.emit("claim_filed", claim.model_dump())

    def key_numbers(self, agent: AgentId, numbers: list[KeyNumber]) -> None:
        self.bus.emit("key_numbers", {"agent": agent.value, "numbers": [n.model_dump() for n in numbers]})

    def view_ready(self, agent: AgentId, stance: float, summary: str) -> None:
        self.bus.emit("view_ready", {"agent": agent.value, "stance": stance, "summary": summary})

    def objection_filed(self, objection: Objection) -> None:
        self.bus.emit("objection_filed", objection.model_dump())

    def rebuttal_filed(self, rebuttal: Rebuttal) -> None:
        self.bus.emit("rebuttal_filed", rebuttal.model_dump())

    def verdict_rendered(self, verdict: Verdict) -> None:
        self.bus.emit("verdict_rendered", verdict.model_dump())

    def valuation_update(
        self,
        football_field: Optional[list[FootballFieldBar]] = None,
        sensitivity: Optional[list[ScenarioCell]] = None,
        sensitivity_axes: Optional[dict[str, list[float]]] = None,
        monte_carlo: Optional[MonteCarloSummary] = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if football_field is not None:
            payload["football_field"] = [b.model_dump() for b in football_field]
        if sensitivity is not None:
            payload["sensitivity"] = [c.model_dump() for c in sensitivity]
        if sensitivity_axes is not None:
            payload["sensitivity_axes"] = sensitivity_axes
        if monte_carlo is not None:
            payload["monte_carlo"] = monte_carlo.model_dump()
        self.bus.emit("valuation_update", payload)

    def geo_exposure(self, geo: GeoExposure) -> None:
        self.bus.emit("geo_exposure", geo.model_dump())

    def conviction_update(self, breakdown: ConvictionBreakdown) -> None:
        self.bus.emit("conviction_update", breakdown.model_dump())

    def thesis_ready(self, thesis: Thesis) -> None:
        self.bus.emit("thesis_ready", thesis.model_dump())

    def rating_ready(self, rating: Rating) -> None:
        self.bus.emit("rating_ready", rating.model_dump())

    def audit_check(self, check: AuditCheck) -> None:
        self.bus.emit("audit_check", check.model_dump())

    def note_published(self, note: ResearchNote) -> None:
        self.bus.emit("note_published", {"run_id": note.run_id})

    def run_failed(self, error: str) -> None:
        self.bus.emit("run_failed", {"error": error})

    def run_complete(self) -> None:
        self.bus.emit("run_complete", {})
        self.bus.close()
