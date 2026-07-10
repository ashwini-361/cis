"""TranscriptStore for accumulating and deduplicating transcription segments."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
        source: Literal["extension", "whisper"] = "extension",
    ) -> None:
        """Add a transcript segment, applying basic deduplication."""
        # Simple dedupe key using start_sec and end_sec rounded to handle minor jitter
        segment_id = f"{participant_id}_{round(start_sec, 1)}_{round(end_sec, 1)}_{source}"
        
        self._sequence_counter += 1
        segment = StoredTranscriptSegment(
            segment_id=segment_id,
            session_id=session_id,
            participant_id=participant_id,
            speaker_name=speaker_name,
            text=text,
            start_sec=start_sec,
            end_sec=end_sec,
            source=source,
            arrival_sequence=self._sequence_counter,
        )

        if session_id not in self._segments:
            self._segments[session_id] = []

        self._segments[session_id].append(segment)
        self._segments[session_id].sort(key=lambda s: (s.start_sec, s.arrival_sequence))

    def get_full_transcript(self, session_id: str) -> list[StoredTranscriptSegment]:
        """Return the accumulated transcript, deduplicating Whisper vs extension."""
        segments = self._segments.get(session_id, [])
        if not segments:
            return []

        # Simplistic resolution: prefer extension over whisper if they overlap heavily
        resolved = []
        for seg in segments:
            # Check overlap with last resolved
            if resolved and seg.start_sec < resolved[-1].end_sec:
                last = resolved[-1]
                if last.source == "extension" and seg.source == "whisper":
                    continue  # Ignore whisper if extension covers it
                elif last.source == "whisper" and seg.source == "extension":
                    resolved[-1] = seg  # Replace whisper with extension
                    continue
            resolved.append(seg)
        return resolved

    def flush(self, session_id: str) -> None:
        """Called at end of session to clean up."""
        if session_id in self._segments:
            logger.info(f"Flushing transcript for session {session_id}")
            # Could persist to a persistent database here
            pass
