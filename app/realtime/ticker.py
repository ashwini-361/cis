"""5-second ticker driving fusion recomputation.

Per docs/ROADMAP.md §3.1 and docs/ARCHITECTURE.md §1.5. Takes an injected
evidence provider instead of a concrete EvidenceStore, and stops after
persisting ParticipantState (no decide()/Verdict emission yet).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from app.fusion.engine import apply_supersedes, fuse
from app.schema import Evidence, ParticipantState
from app.store.state import ParticipantStateStore

GetEvidences = Callable[[str], Awaitable[list[Evidence]]]
SleepFn = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


async def ticker(
    session_id: str,
    participant_ids: list[str],
    get_evidences: GetEvidences,
    state_store: ParticipantStateStore,
    stop_event: asyncio.Event,
    clock: Clock = time.monotonic,
    sleep_fn: SleepFn = asyncio.sleep,
    interval: float = 5.0,
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
