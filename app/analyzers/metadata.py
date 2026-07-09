"""MetadataAnalyzer: name_similarity + email_match evidence per docs/SIGNALS.md §1-2.

Also owns (but per docs/SIGNALS.md §10.3 never emits) device_name -- the
safest behavior for that permanently-disabled signal is silence.
"""

from __future__ import annotations

from rapidfuzz import fuzz, utils

from app.analyzers.base import Analyzer
from app.schema import Event, EventType, Evidence, SessionEnvelope, WeightTable

_LOW_RATIO = 60.0
_HIGH_RATIO = 100.0
_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
_DEVICE_NAME_TOKENS = ("iphone", "ipad", "macbook", "pixel", "galaxy", "laptop", "pc", "desktop")


def _name_similarity_score(display_name: str, candidate_name: str) -> float:
    ratio = fuzz.WRatio(display_name, candidate_name, processor=utils.default_process)
    return max(0.0, min(1.0, (ratio - _LOW_RATIO) / (_HIGH_RATIO - _LOW_RATIO)))


def _normalize_email(email: str) -> str:
    local, _, domain = email.strip().lower().partition("@")
    if domain in _GMAIL_DOMAINS:
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"


def _looks_like_device_name(display_name: str) -> bool:
    lowered = display_name.lower()
    return any(token in lowered for token in _DEVICE_NAME_TOKENS)


class MetadataAnalyzer(Analyzer):
    """Owns name_similarity (0.15), email_match (0.30), device_name (0.00, never emitted)."""

    def __init__(self) -> None:
        self._name_weight = 0.0
        self._email_weight = 0.0
        self._candidate_name: str | None = None
        self._candidate_email: str | None = None
        self._seen: set[tuple[str, int]] = set()

    @property
    def feature(self) -> str:
        return "name_similarity"

    @property
    def source(self) -> str:
        return "metadata_analyzer"

    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        self._name_weight = weights.weights["name_similarity"]
        self._email_weight = weights.weights["email_match"]

    async def on_event(self, event: Event) -> list[Evidence]:
        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen:
            return []
        self._seen.add(key)

        if event.type == EventType.METADATA_CANDIDATE:
            self._candidate_name = event.payload["name"]
            self._candidate_email = event.payload["email"]
            return []

        if event.type in (EventType.PARTICIPANT_JOINED, EventType.PARTICIPANT_RENAMED):
            return self._score_participant(event)

        return []

    def _score_participant(self, event: Event) -> list[Evidence]:
        evidences: list[Evidence] = []
        ts = event.envelope.ts
        participant_id = event.payload["participant_id"]

        if event.type == EventType.PARTICIPANT_JOINED:
            display_name = event.payload["display_name"]
            email = event.payload.get("email")
        else:  # PARTICIPANT_RENAMED -- no email in this payload shape
            display_name = event.payload["new_name"]
            email = None

        if self._candidate_name is not None:
            score = _name_similarity_score(display_name, self._candidate_name)
            if score == 0.0 and _looks_like_device_name(display_name):
                reason = (
                    f"Display name '{display_name}' appears to be a device name, "
                    "not the candidate"
                )
            else:
                reason = f"Display name similarity {score:.0%} to candidate name"
            evidences.append(
                Evidence(
                    session_id=event.envelope.session_id,
                    participant_id=participant_id,
                    feature="name_similarity",
                    source=self.source,
                    score=score,
                    weight=self._name_weight,
                    reason=reason,
                    ts=ts,
                    expires_at=None,
                    supersedes="name_similarity",
                )
            )

        if (
            event.type == EventType.PARTICIPANT_JOINED
            and self._candidate_email is not None
            and email is not None
        ):
            matched = _normalize_email(email) == _normalize_email(self._candidate_email)
            reason = (
                f"Participant's email {email} matched calendar metadata exactly"
                if matched
                else f"Participant's email {email} did not match expected "
                f"{self._candidate_email}"
            )
            evidences.append(
                Evidence(
                    session_id=event.envelope.session_id,
                    participant_id=participant_id,
                    feature="email_match",
                    source=self.source,
                    score=1.0 if matched else 0.0,
                    weight=self._email_weight,
                    reason=reason,
                    ts=ts,
                    expires_at=None,
                    supersedes=None,
                )
            )

        return evidences
