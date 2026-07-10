"""SessionManager tests per the Phase 8 plan."""

from __future__ import annotations

from app.schema import DecayConfig, Verdict, WeightTable
from app.session import SessionManager

_WEIGHT_TABLE = WeightTable(
    version="1.0.0",
    fusion_engine="v1-weighted",
    threshold=0.55,
    margin=0.20,
    decay=DecayConfig(),
    weights={},
)


class FakeWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, object]] = []
        self._fail = fail

    async def send_json(self, data: dict[str, object]) -> None:
        if self._fail:
            raise RuntimeError("connection closed")
        self.sent.append(data)


def _verdict(session_id: str) -> Verdict:
    return Verdict(
        session_id=session_id,
        ts=0.0,
        platform="mock",
        candidate_id=None,
        candidate_name=None,
        confidence=None,
        runner_up_id=None,
        runner_up_confidence=None,
        margin=None,
        reasons=[],
        is_decision=False,
        not_deciding_reason="no participants",
        analyzer_count=0,
        total_evidence=0,
    )


def test_create_and_get_session() -> None:
    manager = SessionManager()
    session = manager.create_session("sess_1", _WEIGHT_TABLE)
    assert manager.get_session("sess_1") is session
    assert manager.get_session("unknown") is None


def test_remove_session() -> None:
    manager = SessionManager()
    manager.create_session("sess_1", _WEIGHT_TABLE)
    manager.remove_session("sess_1")
    assert manager.get_session("sess_1") is None


async def test_broadcast_verdict_updates_latest_and_sends_to_subscribers() -> None:
    manager = SessionManager()
    session = manager.create_session("sess_1", _WEIGHT_TABLE)
    ws = FakeWebSocket()
    manager.add_subscriber("sess_1", ws)

    verdict = _verdict("sess_1")
    await manager.broadcast_verdict("sess_1", verdict)

    assert session.latest_verdict == verdict
    assert len(ws.sent) == 1
    assert ws.sent[0]["session_id"] == "sess_1"


async def test_broadcast_verdict_drops_dead_subscribers() -> None:
    manager = SessionManager()
    manager.create_session("sess_1", _WEIGHT_TABLE)
    good = FakeWebSocket()
    bad = FakeWebSocket(fail=True)
    manager.add_subscriber("sess_1", good)
    manager.add_subscriber("sess_1", bad)

    await manager.broadcast_verdict("sess_1", _verdict("sess_1"))

    assert len(good.sent) == 1
    session = manager.get_session("sess_1")
    assert session is not None
    assert bad not in session.subscribers
    assert good in session.subscribers


async def test_broadcast_verdict_for_unknown_session_is_a_no_op() -> None:
    manager = SessionManager()
    await manager.broadcast_verdict("unknown", _verdict("unknown"))  # must not raise


def test_remove_subscriber() -> None:
    manager = SessionManager()
    session = manager.create_session("sess_1", _WEIGHT_TABLE)
    ws = FakeWebSocket()
    manager.add_subscriber("sess_1", ws)
    manager.remove_subscriber("sess_1", ws)
    assert ws not in session.subscribers


def test_live_debug_snapshot_tracks_ingest_activity() -> None:
    manager = SessionManager()
    manager.create_session("sess_1", _WEIGHT_TABLE)

    manager.mark_extension_connected(
        "sess_1", ts=0.0, message="Meet extension connected to capture ingress"
    )
    manager.record_control_message(
        "sess_1",
        ts=1.0,
        control_type="PARTICIPANT_JOINED",
        payload={"participant_id": "P1"},
    )
    manager.record_audio_chunk(
        "sess_1",
        ts=2.0,
        participant_id="P1",
        start_sec=1.0,
        end_sec=2.0,
        size_bytes=128,
    )
    manager.record_transcript_segment(
        "sess_1",
        ts=3.0,
        participant_id="P1",
        text="I built Astra.",
        start_sec=2.0,
        end_sec=3.0,
        speaker_name="Ashwini",
    )
    manager.record_diagnostic(
        "sess_1",
        ts=4.0,
        kind="content.observer_started",
        message="Meet DOM observers attached",
    )

    snapshot = manager.get_live_debug_snapshot("sess_1")
    assert snapshot is not None
    assert snapshot["extension_connected"] is True
    assert snapshot["control_messages"] == 1
    assert snapshot["audio_chunks"] == 1
    assert snapshot["transcript_segments"] == 1
    assert snapshot["last_transcript"] == {
        "participant_id": "P1",
        "speaker_name": "Ashwini",
        "text": "I built Astra.",
        "start_sec": 2.0,
        "end_sec": 3.0,
    }
    assert any(event["kind"] == "content.observer_started" for event in snapshot["recent_events"])
