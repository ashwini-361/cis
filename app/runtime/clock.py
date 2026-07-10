"""Clock seam — single interface shared by live and harness tick paths.

Live mode wraps :func:`time.monotonic` (returns elapsed seconds since an
arbitrary, non-decreasing origin). Harness mode is stepped explicitly to
each event's ``ts`` so verification and tuning are fully deterministic.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...


class RealClock:
    """Live clock — wraps :func:`time.monotonic`.

    Single-process only (no instance sharing across processes); the
    boundary is the call to ``scheduler.start()``.
    """

    def now(self) -> float:
        return time.monotonic()


class ManualClock:
    """Deterministic stepping clock for tests + the offline harness.

    Holds an explicit ``current`` value (default 0.0) advanced by the
    runner to each event timestamp. ``now()`` returns the held value.
    """

    def __init__(self, current: float = 0.0) -> None:
        self.current = current

    def now(self) -> float:
        return self.current
