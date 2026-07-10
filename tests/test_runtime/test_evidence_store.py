"""EvidenceStore tests: in-memory roundtrip + supersedes semantics."""

from __future__ import annotations

from app.fusion.engine import apply_supersedes
from app.schema import Evidence
from app.store.evidence import EvidenceStore


def _evidence(
    session_id: str,
    participant_id: str,
    feature: str,
    score: float,
    *,
    ts: float = 0.0,
    supersedes: str | None = None,
) -> Evidence:
    return Evidence(
        session_id=session_id,
        participant_id=participant_id,
        feature=feature,
        source="test_analyzer",
        score=score,
        weight=0.1,
        reason=f"test {feature}",
        ts=ts,
        expires_at=None,
        supersedes=supersedes,
    )


async def test_in_memory_append_get_roundtrip() -> None:
    store = EvidenceStore()
    e = _evidence("s", "P1", "email_match", score=1.0)
    await store.append(e)
    out = await store.get("s", "P1")
    assert out == [e]


async def test_in_memory_get_unknown_returns_empty() -> None:
    store = EvidenceStore()
    assert await store.get("nope", "nope") == []


async def test_in_memory_get_all_session_flattens() -> None:
    store = EvidenceStore()
    e1 = _evidence("sess1", "P1", "email_match", score=1.0)
    e2 = _evidence("sess1", "P2", "webcam_usage", score=0.5)
    e3 = _evidence("sess2", "P1", "email_match", score=0.0)
    await store.append(e1)
    await store.append(e2)
    await store.append(e3)
    out = await store.get_all("sess1")
    assert e1 in out and e2 in out
    assert e3 not in out
    assert len(out) == 2


async def test_in_memory_constructor_with_redis_url_is_lazy() -> None:
    """redis_url doesn't attempt network until first op; preserving the
    lazy-init pattern keeps tests free of docker-compose. We assert this
    by constructing without error and without accessing ``_redis``."""

    store = EvidenceStore(redis_url="redis://test:1")
    # Only attempt lazy init when first append/get runs. We don't run it
    # here (would require a live redis) -- just confirm construction.
    assert store._redis is None  # type: ignore[attr-defined]


async def test_supersedes_helper_consistent_with_store() -> None:
    """The store is naïve; apply_supersedes is the single read-time filter."""
    old = _evidence("s", "P1", "transcript_role", score=0.4, ts=0.0)
    new = _evidence(
        "s", "P1", "transcript_role", score=0.92, ts=60.0, supersedes="transcript_role"
    )
    out = apply_supersedes([old, new])
    assert old not in out
    assert new in out
