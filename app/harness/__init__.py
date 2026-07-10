"""Offline harness fixtures + the deterministic accuracy evaluator.

Used by ``scripts/run_accuracy.py`` and ``tests/test_accuracy_harness.py``.
Kept separate from ``app.runtime`` so live code paths never import the
scripted LLM fixtures.
"""
