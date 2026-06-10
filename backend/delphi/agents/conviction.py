"""Transparent conviction scoring.

conviction = base(agreement across specialists)
            − Σ(standing objection weights)
            − citation_penalty

Every component is displayed in the UI with its inputs — no black box.
"""
from __future__ import annotations

import statistics

from .state import AgentView, ConvictionBreakdown, Objection, Verdict


def score(views: list[AgentView], objections: list[Objection],
          verdicts: list[Verdict], uncited_claims: int) -> ConvictionBreakdown:
    stances = [v.stance for v in views] or [0.0]
    mean = statistics.fmean(stances)
    dispersion = statistics.pstdev(stances) if len(stances) > 1 else 0.0

    # Agreement: a unanimous +2 panel reaches ~85 before penalties; a split
    # panel (high dispersion) is haircut even if the mean is bullish.
    base = 50.0 + mean * 17.5 - dispersion * 12.0
    base = max(5.0, min(88.0, base))

    standing_ids = {v.objection_id for v in verdicts if v.status == "standing"}
    mitigated_ids = {v.objection_id for v in verdicts if v.status == "mitigated"}
    objection_penalty = 0.0
    for o in objections:
        if o.id in standing_ids:
            objection_penalty += o.weight
        elif o.id in mitigated_ids:
            objection_penalty += o.weight * 0.35

    citation_penalty = uncited_claims * 3.0

    final = max(0.0, min(100.0, base - objection_penalty - citation_penalty))
    return ConvictionBreakdown(
        base_agreement=round(base, 1),
        objection_penalty=round(objection_penalty, 1),
        citation_penalty=round(citation_penalty, 1),
        final=round(final, 1),
    )
