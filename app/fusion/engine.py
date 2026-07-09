"""v1-weighted fusion engine per docs/DATA_CONTRACT.md §4.3 and docs/ROADMAP.md §3.2."""

from __future__ import annotations

import math

from app.schema import Evidence


def apply_supersedes(evidences: list[Evidence]) -> list[Evidence]:
    """Drop evidence superseded by a later same-participant record.

    Normally EvidenceStore's job (docs/ARCHITECTURE.md §1.4); implemented here
    as a pure helper since the real store isn't built yet. Note: a superseding
    evidence's own `feature` is typically the same key it supersedes (replacing
    the prior record for that feature), so matching must exclude the
    superseding evidence itself and only drop strictly-other, older-or-equal
    records for the same participant + feature.
    """
    to_remove: set[int] = set()
    for e in evidences:
        if e.supersedes is None:
            continue
        for other in evidences:
            if (
                other is not e
                and other.participant_id == e.participant_id
                and other.feature == e.supersedes
                and other.ts <= e.ts
            ):
                to_remove.add(id(other))
    return [e for e in evidences if id(e) not in to_remove]


def fuse(evidences: list[Evidence], t: float) -> float:
    numerator = 0.0
    denominator = 0.0
    for e in evidences:
        if e.expires_at is None:
            decay = 1.0
        else:
            age = max(0.0, t - e.ts)
            half_life = e.expires_at - e.ts
            decay = math.exp(-math.log(2) * age / half_life) if half_life > 0 else 1.0
        numerator += e.weight * e.score * decay
        denominator += e.weight * decay
    if denominator < 1e-6:
        return 0.0
    return numerator / denominator
