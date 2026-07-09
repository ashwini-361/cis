"""SpeakingPatternAnalyzer: speaking_pattern evidence per docs/SIGNALS.md §5.

Turn-taking rules per §5.2: a "candidate turn-taking pattern" is
interviewer-asks -> candidate-answers alternation. Two design decisions not
fully pinned down by the doc (see the Phase 5 plan's discrepancy notes):
(1) the "interviewer->observer" transition rule is applied as a small global
penalty to every tracked participant rather than literally "neutral" (the
doc's own text is self-contradictory here); (2) "identify the interviewer"
skips the doc's "use transcript_role's output" tier entirely, since
analyzers may not call each other (docs/DATA_CONTRACT.md §8.1) -- falls back
to METADATA_INTERVIEWERS, then a most-turn-initiations heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analyzers.base import Analyzer
from app.schema import Event, EventType, Evidence, SessionEnvelope, WeightTable

_WINDOW_SEC = 60.0
_TURN_GAP_SEC = 1.5
_TRANSITION_GAP_SEC = 2.0
_EXPIRES_DELAY_SEC = 300.0
_OBSERVER_PENALTY = 0.2


@dataclass
class _Segment:
    participant_id: str
    start_sec: float
    end_sec: float


@dataclass
class _Turn:
    participant_id: str
    start_sec: float
    end_sec: float


def _partition_into_turns(segments: list[_Segment]) -> list[_Turn]:
    ordered = sorted(segments, key=lambda s: s.start_sec)
    turns: list[_Turn] = []
    for seg in ordered:
        if (
            turns
            and turns[-1].participant_id == seg.participant_id
            and seg.start_sec - turns[-1].end_sec < _TURN_GAP_SEC
        ):
            turns[-1].end_sec = max(turns[-1].end_sec, seg.end_sec)
        else:
            turns.append(_Turn(seg.participant_id, seg.start_sec, seg.end_sec))
    return turns


def _identify_interviewer(
    turns: list[_Turn],
    interviewer_names: list[str] | None,
    display_names: dict[str, str],
) -> str | None:
    if interviewer_names:
        for turn in turns:
            if display_names.get(turn.participant_id) in interviewer_names:
                return turn.participant_id
        return None
    if not turns:
        return None
    initiations: dict[str, int] = {}
    for turn in turns:
        initiations[turn.participant_id] = initiations.get(turn.participant_id, 0) + 1
    return max(initiations, key=lambda pid: initiations[pid])


def _score_participants(
    turns: list[_Turn],
    interviewer_names: list[str] | None,
    display_names: dict[str, str],
) -> dict[str, float]:
    """Per docs/SIGNALS.md §5.2, unifying rules 1 and 4 (see module docstring):
    whenever the interviewer's turn is followed by participant b's turn, b
    gets +1 (interviewer->candidate credit) while every *other* tracked
    participant gets a small -0.2 penalty (interviewer engaged someone else
    instead of them -- this is the doc's "interviewer->observer" rule, from
    every other participant's perspective simultaneously).
    """
    participants = {turn.participant_id for turn in turns}
    if not participants:
        return {}
    interviewer = _identify_interviewer(turns, interviewer_names, display_names)
    raw: dict[str, float] = dict.fromkeys(participants, 0.0)

    for i in range(len(turns) - 1):
        a, b = turns[i], turns[i + 1]
        if b.start_sec - a.end_sec > _TRANSITION_GAP_SEC:
            continue
        if a.participant_id == interviewer and b.participant_id != interviewer:
            for pid in raw:
                raw[pid] += 1.0 if pid == b.participant_id else -_OBSERVER_PENALTY
        elif a.participant_id != interviewer and b.participant_id == interviewer:
            pass  # candidate asks interviewer -- neutral
        elif a.participant_id != interviewer and b.participant_id != interviewer:
            raw[a.participant_id] -= 0.5

    denom = max(max(raw.values(), default=0.0), 1.0)
    return {pid: max(0.0, min(1.0, score / denom)) for pid, score in raw.items()}


class SpeakingPatternAnalyzer(Analyzer):
    """Owns speaking_pattern (0.15). Re-fires every 5s via on_tick."""

    def __init__(self) -> None:
        self._weight = 0.0
        self._session_id: str | None = None
        self._interviewer_names: list[str] | None = None
        self._display_names: dict[str, str] = {}
        self._segments: list[_Segment] = []
        self._seen: set[tuple[str, int]] = set()

    @property
    def feature(self) -> str:
        return "speaking_pattern"

    @property
    def source(self) -> str:
        return "speaking_pattern_analyzer"

    async def initialize(self, weights: WeightTable, session: SessionEnvelope) -> None:
        self._weight = weights.weights["speaking_pattern"]
        self._session_id = session.session_id

    async def on_event(self, event: Event) -> list[Evidence]:
        key = (event.envelope.source, event.envelope.sequence)
        if key in self._seen:
            return []
        self._seen.add(key)

        if event.type == EventType.METADATA_INTERVIEWERS:
            self._interviewer_names = event.payload["names"]
            return []

        if event.type == EventType.PARTICIPANT_JOINED:
            self._display_names[event.payload["participant_id"]] = event.payload["display_name"]
            return []

        if event.type == EventType.TRANSCRIPT_SEGMENT:
            self._segments.append(
                _Segment(
                    participant_id=event.payload["participant_id"],
                    start_sec=event.payload["start_sec"],
                    end_sec=event.payload["end_sec"],
                )
            )
            return []

        return []

    async def on_tick(self, t: float) -> list[Evidence]:
        assert self._session_id is not None, "initialize() must be called before on_tick"
        window = [s for s in self._segments if t - s.start_sec <= _WINDOW_SEC]
        turns = _partition_into_turns(window)
        scores = _score_participants(turns, self._interviewer_names, self._display_names)

        return [
            Evidence(
                session_id=self._session_id,
                participant_id=participant_id,
                feature="speaking_pattern",
                source=self.source,
                score=score,
                weight=self._weight,
                reason="Speaking pattern matched candidate turn-taking"
                if score >= 0.5
                else "Speaking pattern did not match candidate turn-taking",
                ts=t,
                expires_at=t + _EXPIRES_DELAY_SEC,
                supersedes="speaking_pattern",
            )
            for participant_id, score in scores.items()
        ]
