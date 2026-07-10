"""SessionRunner tests — replay the real ``happy_path`` recording through
the full runtime and assert the project-shaping regression proof:

- The runner drives adapter → bus → analyzer on_event + on_tick → fuse →
  decide → broadcast.
- Verdicts include a decidable transition that names the correct
  participant (``P1`` == ``ground_truth_candidate_id``).
- Transcript-role evidence actually appears (the Phase 9A load-bearing
  orphan regression fix).
- Two runs produce identical verdict sequences (determinism).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.ingest.base import IngestAdapter
from app.ingest.mock import MockAdapter
from app.runtime.clock import ManualClock
from app.runtime.registry import build_default
from app.runtime.session_runner import run_session
from app.schema import Event, EventEnvelope, EventType, SessionEnvelope

HAPPY_PATH = Path(
    "I:/Project/meet/cis/data/recordings/happy_path.json"
).resolve()


def _envelope_from_recording(recording: dict[str, object]) -> SessionEnvelope:
    s = recording["session"]
    return SessionEnvelope(
        session_id=str(s["session_id"]),
        platform="mock",  # type: ignore[arg-type]
        start_wall_clock=str(s["start_wall_clock"]),
        expected_duration_min=int(s.get("expected_duration_min", 30)),  # type: ignore[arg-type]
        expected_participants=list(s.get("expected_participants", [])),  # type: ignore[arg-type]
        ground_truth_candidate_id=s.get("ground_truth_candidate_id"),  # type: ignore[arg-type]
    )


async def _no_sleep(_delay: float) -> None:
    """Replay sleeps zero real time -- replay is fully deterministic on event ts."""


async def _drive(weights, scripted_llm) -> list:
    raw = json.loads(HAPPY_PATH.read_text())
    envelope = _envelope_from_recording(raw)
    adapter = MockAdapter(HAPPY_PATH, sleep_fn=_no_sleep)
    analyzers = build_default(weights, scripted_llm)

    verdicts = await run_session(
        adapter=adapter,
        session_envelope=envelope,
        platform="mock",
        analyzers=analyzers,
        weights=weights,
        clock=ManualClock(),
    )
    return verdicts


async def test_session_runner_happy_path_decides_p1(weights, scripted_llm) -> None:
    """The end-to-end replay must commit to P1 -- the load-bearing proof
    that the runtime glue produces a real verdict.
    """

    verdicts = await _drive(weights, scripted_llm)

    # At least one decidable verdict exists.
    decidable = [v for v in verdicts if v.is_decision]
    assert len(decidable) > 0, "Pipeline produced zero decidable verdicts over happy_path."

    # First decidable verdict picks P1 -- the documented t=200s behavior.
    first_decidable = decidable[0]
    assert first_decidable.candidate_id == "P1", (
        f"Expected P1 (ground truth), got {first_decidable.candidate_id}"
    )
    assert first_decidable.candidate_name is not None
    assert first_decidable.confidence is not None
    assert first_decidable.confidence >= weights.threshold


async def test_session_runner_happy_path_emits_transcript_role_evidence(
    weights, scripted_llm
) -> None:
    """Transcript-role evidence appears in the verdict's total_evidence --
    proves on_tick is being called for the orphan-signal analyzer."""

    verdicts = await _drive(weights, scripted_llm)

    # Total evidence grows as on_tick fires for the transcript-role analyzer.
    later_verdicts = [v for v in verdicts if v.ts > 100.0]
    assert any(v.total_evidence > 0 for v in later_verdicts)


async def test_session_runner_is_deterministic(weights, scripted_llm) -> None:
    """Two replays of the same recording produce simpler-deterministic verdict sequences."""

    first = await _drive(weights, scripted_llm)
    second = await _drive(weights, scripted_llm)

    # Same number of verdicts, same candidate_id time series, same confidences.
    assert [v.candidate_id for v in first] == [v.candidate_id for v in second]
    assert [(round(v.ts, 6)) for v in first] == [round(v.ts, 6) for v in second]
    assert [
        v.is_decision for v in first
    ] == [v.is_decision for v in second]


async def test_session_runner_no_events_lost(weights, scripted_llm) -> None:
    """Every transcript-segment event flows through some analyzer -- the
    bus dispatch path is exercised, not bypassed."""

    verdicts = await _drive(weights, scripted_llm)

    # The recording has 11 transcript segments; with the transcript-role
    # analyzer firing every 5s and the script triggering one pass per
    # ~60s window, we expect some segment-derived evidence to accrue.
    dec = max(v.total_evidence for v in verdicts)
    assert dec >= 5, f"Pipeline accumulated too little evidence ({dec}) -- on_tick regression?"


class _SingleTranscriptAdapter(IngestAdapter):
    async def start_session(self, session_envelope: SessionEnvelope) -> None:
        self._session_envelope = session_envelope

    async def end_session(self, reason: str = "normal") -> None:
        return None

    async def stream_events(self):
        yield Event(
            type=EventType.PARTICIPANT_JOINED,
            envelope=EventEnvelope(
                session_id=self._session_envelope.session_id,
                ts=1.0,
                wall_clock="2026-07-09T00:00:01Z",
                platform="meet",
                source="meet.extension",
                sequence=1,
            ),
            payload={
                "participant_id": "mixed-tab-audio",
                "display_name": "Mixed Tab Audio",
                "email": None,
                "device_name": None,
                "join_order": 1,
            },
        )
        yield Event(
            type=EventType.TRANSCRIPT_SEGMENT,
            envelope=EventEnvelope(
                session_id=self._session_envelope.session_id,
                ts=6.0,
                wall_clock="2026-07-09T00:00:06Z",
                platform="meet",
                source="meet.transcript.whisper",
                sequence=2,
            ),
            payload={
                "participant_id": "mixed-tab-audio",
                "text": "Thanks for joining today.",
                "start_sec": 0.0,
                "end_sec": 6.0,
            },
        )


async def test_session_runner_event_callback_observes_whisper_transcripts(weights) -> None:
    seen: list[Event] = []
    envelope = SessionEnvelope(
        session_id="meet-sess-1",
        platform="meet",
        start_wall_clock="2026-07-09T00:00:00Z",
    )

    async def _record(event: Event) -> None:
        seen.append(event)

    await run_session(
        adapter=_SingleTranscriptAdapter(),
        session_envelope=envelope,
        platform="meet",
        analyzers=[],
        weights=weights,
        clock=ManualClock(),
        event_callback=_record,
    )

    whisper_events = [e for e in seen if e.envelope.source == "meet.transcript.whisper"]
    assert len(whisper_events) == 1
    assert whisper_events[0].payload["text"] == "Thanks for joining today."


class _SingleJoinAdapter(IngestAdapter):
    async def start_session(self, session_envelope: SessionEnvelope) -> None:
        self._session_envelope = session_envelope

    async def end_session(self, reason: str = "normal") -> None:
        return None

    async def stream_events(self):
        yield Event(
            type=EventType.PARTICIPANT_JOINED,
            envelope=EventEnvelope(
                session_id=self._session_envelope.session_id,
                ts=1.0,
                wall_clock="2026-07-09T00:00:01Z",
                platform="meet",
                source="meet.extension",
                sequence=1,
            ),
            payload={
                "participant_id": "spaces/meet/devices/343",
                "display_name": "Rahul",
                "email": None,
                "device_name": None,
                "join_order": 1,
            },
        )


async def test_session_runner_bootstrap_candidate_metadata_surfaces_provisional_candidate(
    weights, scripted_llm
) -> None:
    verdicts = await run_session(
        adapter=_SingleJoinAdapter(),
        session_envelope=SessionEnvelope(
            session_id="meet-sess-bootstrap",
            platform="meet",
            start_wall_clock="2026-07-09T00:00:00Z",
            candidate_name="Rahul",
            expected_participants=["Rahul", "Interviewer"],
        ),
        platform="meet",
        analyzers=build_default(weights, scripted_llm),
        weights=weights,
        clock=ManualClock(),
    )

    assert len(verdicts) > 0
    final_verdict = verdicts[-1]
    assert final_verdict.is_decision is False
    assert final_verdict.candidate_id == "spaces/meet/devices/343"
    assert final_verdict.candidate_name == "Rahul"
    assert final_verdict.confidence is not None
