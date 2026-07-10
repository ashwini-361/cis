"""TranscriptStore for accumulating and deduplicating transcription segments."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredTranscriptSegment:
    segment_id: str
    session_id: str
    participant_id: str
    speaker_name: str | None
    text: str
    start_sec: float
    end_sec: float
    source: Literal["extension", "whisper"]
    arrival_sequence: int


class TranscriptStore:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis = None
        self._segments: dict[str, list[StoredTranscriptSegment]] = {}
        self._sequence_counter: int = 0

    def add_segment(
        self,
        session_id: str,
        participant_id: str,
        speaker_name: str | None,
        text: str,
        start_sec: float,
        end_sec: float,
        source: str = "extension",
    ) -> None:
        normalized_source: Literal["extension", "whisper"] = (
            "whisper" if source.endswith("whisper") else "extension"
        )
        segment_id = (
            f"{participant_id}_{round(start_sec, 1)}_{round(end_sec, 1)}_{normalized_source}"
        )

        if session_id not in self._segments:
            self._segments[session_id] = []

        existing = self._segments[session_id]
        for seg in existing:
            if seg.segment_id == segment_id:
                return

        self._sequence_counter += 1
        segment = StoredTranscriptSegment(
            segment_id=segment_id,
            session_id=session_id,
            participant_id=participant_id,
            speaker_name=speaker_name,
            text=text,
            start_sec=start_sec,
            end_sec=end_sec,
            source=normalized_source,
            arrival_sequence=self._sequence_counter,
        )

        existing.append(segment)
        existing.sort(key=lambda s: (s.start_sec, s.arrival_sequence))

    def get_full_transcript(self, session_id: str) -> list[StoredTranscriptSegment]:
        segments = self._segments.get(session_id, [])
        if not segments:
            return []

        resolved: list[StoredTranscriptSegment] = []
        seen_ids: set[str] = set()

        for seg in segments:
            if seg.segment_id in seen_ids:
                continue
            seen_ids.add(seg.segment_id)

            if resolved and seg.start_sec < resolved[-1].end_sec:
                last = resolved[-1]
                if last.segment_id == seg.segment_id:
                    continue
                seg_duration = max(seg.end_sec - seg.start_sec, 0.01)
                overlap_frac = (resolved[-1].end_sec - seg.start_sec) / seg_duration
                if last.source == "extension" and seg.source == "whisper":
                    if overlap_frac > 0.5:
                        continue
                elif last.source == "whisper" and seg.source == "extension":
                    if overlap_frac > 0.5:
                        resolved[-1] = seg
                        continue
                elif last.source == "whisper" and seg.source == "whisper":
                    if overlap_frac > 0.5 and len(seg.text) < len(last.text):
                        continue
            resolved.append(seg)
        return resolved

    def flush(self, session_id: str) -> None:
        """Called at end of session to clean up."""
        if session_id in self._segments:
            logger.info(f"Flushing transcript for session {session_id}")
            # Could persist to a persistent database here
            pass
