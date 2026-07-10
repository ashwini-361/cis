"""REST routes per docs/API_SPECIFICATION.md."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
