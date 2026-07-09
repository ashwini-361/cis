"""5-second ticker driving fusion recomputation.

Per docs/ROADMAP.md §3.1 and docs/ARCHITECTURE.md §1.5. Takes an injected
evidence provider instead of a concrete EvidenceStore. Extended in Phase 8 to
close the fuse -> decide -> broadcast loop each tick (deferred from Phase 3
until decide()/Explainer/Verdict existed).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.explain.generator import Explainer
from app.fusion.engine import apply_supersedes, decide, fuse
from app.schema import Evidence, ParticipantState, Verdict
from app.store.state import ParticipantStateStore

GetEvidences = Callable[[str], Awaitable[list[Evidence]]]
SleepFn = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
Broadcast = Callable[[Verdict], Awaitable[None]]


async def ticker(
    session_id: str,
    platform: str,
    participant_ids: list[str],
    get_evidences: GetEvidences,
    state_store: ParticipantStateStore,
    stop_event: asyncio.Event,
    explainer: Explainer,
    broadcast: Broadcast,
    clock: Clock = time.monotonic,
    sleep_fn: SleepFn = asyncio.sleep,
    interval: float = 5.0,
    threshold: float = 0.55,
    margin: float = 0.20,
) -> None:
    while not stop_event.is_set():
        await sleep_fn(interval)
        t = clock()
        for participant_id in participant_ids:
            evidences = apply_supersedes(await get_evidences(participant_id))
            confidence = fuse(evidences, t)
            existing = await state_store.get(session_id, participant_id)
            if existing is None:
                existing = ParticipantState(
                    session_id=session_id,
                    participant_id=participant_id,
                    display_name=participant_id,
                    join_ts=t,
                )
            updated = existing.model_copy(
                update={
                    "confidence": confidence,
                    "raw_evidence": evidences,
                    "last_recompute_ts": t,
                    "total_evidence": len(evidences),
                }
            )
            await state_store.set(updated)

        all_states = await state_store.get_all(session_id)
        verdict = decide(session_id, platform, all_states, t, explainer, threshold, margin)
        await broadcast(verdict)
