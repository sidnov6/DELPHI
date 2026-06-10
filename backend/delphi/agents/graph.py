"""Debate graph — nodes, conditional edges, the one allowed revision loop.

PLAN → PARALLEL_RESEARCH → ADVERSARY_ROUND_1 → REBUTTAL → ADVERSARY_ROUND_2
     → SYNTHESIS → AUDIT → PUBLISH | REVISE (loops back to AUDIT once)

A LangGraph-style typed state machine without the dependency: the debate
classes own the node implementations; this module owns run lifecycle, mode
selection (live vs simulation) and failure surfaces.
"""
from __future__ import annotations

import asyncio
import os
import traceback
import uuid
from pathlib import Path
from typing import Any

from ..data.bundle import load_bundle
from . import analysis
from .events import EventBus, Emitter
from .state import ResearchState


def _load_env_file() -> None:
    """Minimal backend/.env loader — keys never live in code or git."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()


def live_provider() -> str | None:
    """Anthropic wins if both keys are present; Groq otherwise."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return None


def has_live_mode() -> bool:
    return live_provider() is not None


class Run:
    def __init__(self, ticker: str, mode: str | None = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.ticker = ticker.upper()
        self.bus = EventBus()
        self.state = ResearchState(run_id=self.id, ticker=self.ticker)
        requested = mode or ("live" if has_live_mode() else "simulation")
        self.mode = "live" if (requested == "live" and has_live_mode()) else "simulation"
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        from .state import Phase

        emit = Emitter(self.bus)
        try:
            # Dynamic coverage takes a few seconds to source — show life
            # immediately. The debate re-emits both events with full detail.
            emit.run_started(self.id, self.ticker, self.ticker, self.mode)
            emit.phase_changed(Phase.PLAN, "Sourcing filings, tape and consensus…")
            online = os.environ.get("DELPHI_OFFLINE", "0") != "1"
            bundle: dict[str, Any] = await asyncio.to_thread(load_bundle, self.ticker, online)
            valuation = await asyncio.to_thread(analysis.run_valuation, bundle)
            self.state.company = bundle["company"]
            self.state.mode = self.mode  # type: ignore[assignment]

            if self.mode == "live" and live_provider() == "anthropic":
                from .llm import LiveDebate
                debate = LiveDebate(self.state, bundle, valuation, emit)
            elif self.mode == "live" and live_provider() == "groq":
                from .groq import GroqDebate
                debate = GroqDebate(self.state, bundle, valuation, emit)
            else:
                from .sim import SimDebate
                debate = SimDebate(self.state, bundle, valuation, emit)
            await debate.run()
        except Exception as exc:
            traceback.print_exc()
            emit.run_failed(str(exc))
            self.bus.close()


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, ticker: str, mode: str | None = None) -> Run:
        run = Run(ticker, mode)
        self._runs[run.id] = run
        run.start()
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)


registry = RunRegistry()
