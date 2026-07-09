"""Pydantic wire schema per docs/DATA_CONTRACT.md sections 1-8."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    """Base for every wire model: immutable per Phase 1 do-done criteria."""

    model_config = ConfigDict(frozen=True)


# --- 1. EventType + Event (DATA_CONTRACT.md §2) -----------------------------


class EventType(str, Enum):  # noqa: UP042 -- matches docs/DATA_CONTRACT.md §2.1 verbatim
    PARTICIPANT_JOINED = "participant.joined"
    PARTICIPANT_LEFT = "participant.left"
    PARTICIPANT_RENAMED = "participant.renamed"
    WEBCAM_ON = "webcam.on"
    WEBCAM_OFF = "webcam.off"
    SCREEN_SHARE_START = "screen_share.start"
    SCREEN_SHARE_STOP = "screen_share.stop"
    AUDIO_ACTIVE = "audio.active"
    AUDIO_SILENT = "audio.silent"
    AUDIO_CHUNK = "audio.chunk"
    VIDEO_FRAME = "video.frame"
    SCREEN_FRAME = "screen.frame"
    TRANSCRIPT_SEGMENT = "transcript.segment"
    METADATA_CANDIDATE = "metadata.candidate"
    METADATA_SCHEDULE = "metadata.schedule"
    METADATA_INTERVIEWERS = "metadata.interviewers"
    SESSION_START = "session.start"
    SESSION_END = "session.end"


class EventEnvelope(_Frozen):
    session_id: str
    ts: float
    wall_clock: str
    platform: Literal["zoom", "meet", "teams", "mock"]
    source: str
    sequence: int


class Event(_Frozen):
    type: EventType
    envelope: EventEnvelope
    payload: dict[str, Any]

    def parsed_payload(self) -> BaseModel:
        """Validate self.payload into its typed model per PAYLOAD_MODELS.

        Opt-in helper for analyzers; does not change the wire shape of `payload`.
        """
        model = PAYLOAD_MODELS[self.type]
        return model.model_validate(self.payload)


# --- 2. Per-EventType payload models (DATA_CONTRACT.md §2.2) ---------------


class WordTiming(_Frozen):
    token: str
    start_sec: float
    end_sec: float
    confidence: float = Field(ge=0.0, le=1.0)


class ParticipantJoinedPayload(_Frozen):
    participant_id: str
    display_name: str
    email: str | None = None
    device_name: str | None = None
    join_order: int


class ParticipantLeftPayload(_Frozen):
    participant_id: str
    leave_ts: float


class ParticipantRenamedPayload(_Frozen):
    participant_id: str
    old_name: str
    new_name: str


class WebcamOnPayload(_Frozen):
    participant_id: str


class WebcamOffPayload(_Frozen):
    participant_id: str


class ScreenShareStartPayload(_Frozen):
    participant_id: str


class ScreenShareStopPayload(_Frozen):
    participant_id: str


class AudioActivePayload(_Frozen):
    participant_id: str
    duration_sec: float


class AudioSilentPayload(_Frozen):
    participant_id: str
    duration_sec: float


class AudioChunkPayload(_Frozen):
    participant_id: str
    format: Literal["wav", "opus"]
    sample_rate: int
    channels: int
    base64_bytes: str
    start_sec: float
    end_sec: float


class VideoFramePayload(_Frozen):
    participant_id: str
    format: Literal["jpeg"]
    width: int
    height: int
    base64_bytes: str


class ScreenFramePayload(_Frozen):
    participant_id: str | None = None
    format: Literal["jpeg"]
    width: int
    height: int
    base64_bytes: str


class TranscriptSegmentPayload(_Frozen):
    participant_id: str
    text: str
    start_sec: float
    end_sec: float
    words: list[WordTiming] | None = None


class MetadataCandidatePayload(_Frozen):
    name: str
    email: str
    calendar_invite_id: str | None = None


class MetadataSchedulePayload(_Frozen):
    start_wall_clock: str
    expected_duration_min: int
    interviewer_names: list[str]


class MetadataInterviewersPayload(_Frozen):
    names: list[str]
    emails: list[str] | None = None


class SessionStartPayload(_Frozen):
    expected_participants: list[str]


class SessionEndPayload(_Frozen):
    reason: Literal["normal", "timeout", "error"]


PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.PARTICIPANT_JOINED: ParticipantJoinedPayload,
    EventType.PARTICIPANT_LEFT: ParticipantLeftPayload,
    EventType.PARTICIPANT_RENAMED: ParticipantRenamedPayload,
    EventType.WEBCAM_ON: WebcamOnPayload,
    EventType.WEBCAM_OFF: WebcamOffPayload,
    EventType.SCREEN_SHARE_START: ScreenShareStartPayload,
    EventType.SCREEN_SHARE_STOP: ScreenShareStopPayload,
    EventType.AUDIO_ACTIVE: AudioActivePayload,
    EventType.AUDIO_SILENT: AudioSilentPayload,
    EventType.AUDIO_CHUNK: AudioChunkPayload,
    EventType.VIDEO_FRAME: VideoFramePayload,
    EventType.SCREEN_FRAME: ScreenFramePayload,
    EventType.TRANSCRIPT_SEGMENT: TranscriptSegmentPayload,
    EventType.METADATA_CANDIDATE: MetadataCandidatePayload,
    EventType.METADATA_SCHEDULE: MetadataSchedulePayload,
    EventType.METADATA_INTERVIEWERS: MetadataInterviewersPayload,
    EventType.SESSION_START: SessionStartPayload,
    EventType.SESSION_END: SessionEndPayload,
}


# --- 3. Evidence (DATA_CONTRACT.md §3) --------------------------------------


class Evidence(_Frozen):
    session_id: str
    participant_id: str
    feature: str
    source: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=240)
    raw_payload: dict[str, Any] = Field(default_factory=dict, exclude=True)
    ts: float
    expires_at: float | None = None
    supersedes: str | None = None


# --- 4. ParticipantState (DATA_CONTRACT.md §4) ------------------------------
# NOTE: frozen=True; "updated every 5s" (§4.2) means future callers construct a
# new instance via `state.model_copy(update={...})` — frozen only blocks
# in-place attribute assignment, not construction of a modified copy.


class ParticipantState(_Frozen):
    session_id: str
    participant_id: str
    display_name: str
    email: str | None = None
    device_name: str | None = None
    join_ts: float
    is_present: bool = True
    confidence: float = 0.0
    raw_evidence: list[Evidence] = Field(default_factory=list)
    last_recompute_ts: float = 0.0
    analyzer_count: int = 0
    total_evidence: int = 0


# --- 5. RejectedHypothesis + Verdict (DATA_CONTRACT.md §5) ------------------


class RejectedHypothesis(_Frozen):
    participant_id: str
    display_name: str
    confidence: float
    top_negative_reasons: list[str]


class Verdict(_Frozen):
    session_id: str
    ts: float
    platform: str
    candidate_id: str | None
    candidate_name: str | None
    confidence: float | None
    runner_up_id: str | None
    runner_up_confidence: float | None
    margin: float | None
    reasons: list[str]
    rejected_hypotheses: list[RejectedHypothesis] = Field(default_factory=list)
    is_decision: bool
    not_deciding_reason: str | None = None
    analyzer_count: int
    total_evidence: int
    engine_version: str = "v1-weighted"


# --- 6. WeightTable (DATA_CONTRACT.md §6) -----------------------------------


class DecayConfig(_Frozen):
    default_half_life_sec: float = 300.0
    # dict[str, float | None]: weights.json ships `null` for sticky/no-decay
    # features (name_similarity, email_match) — widened from DATA_CONTRACT.md's
    # literal `dict[str, float]` to accept that committed v1.0 content as-is.
    per_feature: dict[str, float | None] = Field(default_factory=dict)


class WeightTable(_Frozen):
    version: str
    fusion_engine: Literal["v1-weighted", "v2-bayesian"]
    threshold: float = Field(ge=0.0, le=1.0)
    margin: float = Field(ge=0.0, le=1.0)
    decay: DecayConfig
    weights: dict[str, float]


# --- 7. SessionEnvelope (DATA_CONTRACT.md §7) -------------------------------


class SessionEnvelope(_Frozen):
    session_id: str
    platform: Literal["zoom", "meet", "teams", "mock"]
    start_wall_clock: str
    expected_duration_min: int = 60
    expected_participants: list[str] = Field(default_factory=list)
    ground_truth_candidate_id: str | None = None
    notes: str = ""
