"""WeightTable loader — thin re-export of config.load_weights for import ergonomics.

The canonical implementation lives in app.config; this module exists so that
callers can do ``from app.fusion.weights import load_weights`` without knowing
where the loader lives.
"""

from app.config import load_weights as load_weights  # noqa: PLC0414 -- re-export
