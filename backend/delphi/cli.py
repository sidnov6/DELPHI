"""`delphi run NVDA` — run a debate in the terminal, print the note JSON."""
from __future__ import annotations

import asyncio
import json
import sys


async def _main(ticker: str) -> None:
    from .agents.graph import Run

    run = Run(ticker)
    run.start()
    q = run.bus.subscribe()
    while True:
        ev = await q.get()
        if ev is None:
            break
        t, d = ev["type"], ev["data"]
        if t == "phase_changed":
            print(f"\n━━ {d['phase']} — {d.get('detail', '')}", file=sys.stderr)
        elif t == "message_delta":
            print(d["text"], end="", file=sys.stderr, flush=True)
        elif t == "message_end":
            print(file=sys.stderr)
        elif t == "tool_call":
            print(f"  ⚙ {d['agent']} → {d['tool']}({d['args']})", file=sys.stderr)
        elif t == "objection_filed":
            print(f"  ⚔ OBJECTION [{d['id']}] vs {d['target_agent']} (w={d['weight']})", file=sys.stderr)
        elif t == "verdict_rendered":
            print(f"  ⚖ {d['objection_id']}: {d['status'].upper()}", file=sys.stderr)
        elif t == "run_failed":
            print(f"\nRUN FAILED: {d['error']}", file=sys.stderr)
            sys.exit(1)
    if run.state.note:
        print(json.dumps(run.state.note.model_dump(), indent=2))


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] != "run":
        print("usage: python -m delphi.cli run <TICKER>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(_main(sys.argv[2]))


if __name__ == "__main__":
    main()
