"""REST routes per docs/API_SPECIFICATION.md."""
from __future__ import annotations

import os
import tempfile
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


class WhisperTestRequest(BaseModel):
    """Request model for whisper test endpoint."""
    audio_path: str
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"


class WhisperTestResponse(BaseModel):
    """Response model for whisper test endpoint."""
    success: bool
    transcription: str | None = None
    segments: list[dict] | None = None
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None
    error: str | None = None


@router.post("/test/whisper", response_model=WhisperTestResponse)
async def test_whisper(
    audio_path: str = Form(...),
    model_size: str = Form("small"),
    device: str = Form("cpu"),
    compute_type: str = Form("int8"),
) -> WhisperTestResponse:
    """Test Whisper transcription on a local audio file.

    Args:
        audio_path: Path to the audio file (WAV, MP3, WebM, etc.)
        model_size: Whisper model size (tiny, base, small, medium, large-v1, large-v2, large-v3, large-v3-turbo)
        device: Device to use (auto, cpu, cuda)
        compute_type: Compute type (default, int8, int8_float16, float16, float32)

    Returns:
        Transcription result with segments and metadata
    """
    try:
        # Check if file exists
        if not os.path.exists(audio_path):
            return WhisperTestResponse(
                success=False,
                error=f"Audio file not found: {audio_path}"
            )

        # Import faster-whisper
        from faster_whisper import WhisperModel

        # Load model
        logger.info(f"Loading Whisper model: {model_size} on {device}/{compute_type}")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        # Transcribe
        logger.info(f"Transcribing: {audio_path}")
        segments, info = model.transcribe(audio_path)

        segment_list = []
        full_text = []
        for seg in segments:
            segment_list.append({
                "text": seg.text.strip(),
                "start": seg.start,
                "end": seg.end
            })
            full_text.append(seg.text.strip())

        return WhisperTestResponse(
            success=True,
            transcription=" ".join(full_text),
            segments=segment_list,
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration
        )

    except Exception as e:
        logger.exception("Whisper transcription failed")
        return WhisperTestResponse(
            success=False,
            error=str(e)
        )


@router.post("/test/whisper/upload", response_model=WhisperTestResponse)
async def test_whisper_upload(
    audio_file: UploadFile = File(...),
    model_size: str = Form("small"),
    device: str = Form("cpu"),
    compute_type: str = Form("int8"),
) -> WhisperTestResponse:
    """Test Whisper transcription by uploading an audio file.

    Args:
        audio_file: Uploaded audio file (WAV, MP3, WebM, etc.)
        model_size: Whisper model size
        device: Device to use (auto, cpu, cuda)
        compute_type: Compute type (default, int8, int8_float16, float16, float32)

    Returns:
        Transcription result with segments and metadata
    """
    tmp_path = None
    try:
        # Save uploaded file to temp location
        suffix = os.path.splitext(audio_file.filename or "audio.wav")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio_file.read()
            tmp.write(content)
            tmp_path = tmp.name

        logger.info(f"Uploaded file saved to: {tmp_path} ({len(content)} bytes)")

        # Import faster-whisper
        from faster_whisper import WhisperModel

        # Load model
        logger.info(f"Loading Whisper model: {model_size} on {device}/{compute_type}")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        # Transcribe
        logger.info(f"Transcribing uploaded file...")
        segments, info = model.transcribe(tmp_path)

        segment_list = []
        full_text = []
        for seg in segments:
            segment_list.append({
                "text": seg.text.strip(),
                "start": seg.start,
                "end": seg.end
            })
            full_text.append(seg.text.strip())

        return WhisperTestResponse(
            success=True,
            transcription=" ".join(full_text),
            segments=segment_list,
            language=info.language,
            language_probability=info.language_probability,
            duration=info.duration
        )

    except Exception as e:
        logger.exception("Whisper transcription failed")
        return WhisperTestResponse(
            success=False,
            error=str(e)
        )
    finally:
        # Cleanup temp file
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
