"""Weights/config loader per docs/DATA_CONTRACT.md §6.

Loads ``data/weights/weights.json`` into a validated ``WeightTable``. Kept
small on purpose (a pydantic BaseSettings layer is overkill for a single
JSON file that already validates against the schema).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schema import WeightTable

_DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "weights" / "weights.json"


def load_weights(path: Path | str | None = None) -> WeightTable:
    """Load a weight table from a JSON file path.

    A ``None`` path (the common case) resolves to the committed
    ``data/weights/weights.json`` — the single source of truth for the
    v1.0 default weight set, threshold, and margin.
    """

    resolved = Path(path) if path is not None else _DEFAULT_WEIGHTS_PATH
    return WeightTable.model_validate(json.loads(resolved.read_text()))
