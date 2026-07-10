#!/usr/bin/env python
"""scripts/tune.py \u2014 coordinate-descent weight calibration.

Per docs/ACCURACY_METRICS.md \u00a76:
  - Reads all labeled recordings from ``data/recordings/``
  - Runs coordinate descent to maximise:
      p\u00e01 \u2212 0.001\u00d7flips + 0.0001\u00d7(600\u2212t2d)
  - Writes ``data/weights/weights.v1.1.json`` + ``tuning_report.v1.1.md``

Hard rules (\u00a76.5):
  - ``face_consistency`` / ``device_name`` stay 0.0 without \u22655 vision recordings
  - All weights in [0, 1]
  - Abort with RuntimeError if baseline p@1 < 0.7 before tuning

Usage:
    uv run python scripts/tune.py [--recordings PATH] [--iterations N]

``evaluate`` and ``tune`` are importable by tests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import load_weights  # noqa: E402
from app.harness.metrics import flips, precision_at_1, time_to_decision  # noqa: E402
from app.harness.scripted_llm import ScriptedLLMProvider  # noqa: E402
from app.ingest.mock import MockAdapter  # noqa: E402
from app.runtime.clock import ManualClock  # noqa: E402
from app.runtime.registry import build_default  # noqa: E402
from app.runtime.session_runner import run_session  # noqa: E402
from app.schema import SessionEnvelope, Verdict, WeightTable  # noqa: E402

# Features that are currently unimplemented / require vision recordings to be
# meaningful.  Per \u00a76.5 they cannot be enabled without \u22655 vision recordings.
_VISION_GUARDED: frozenset[str] = frozenset({"face_consistency", "device_name"})
_COORD_DELTAS = [-0.05, -0.02, -0.01, 0.0, +0.01, +0.02, +0.05]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _no_sleep(_: float) -> None:
    pass


def _make_envelope(recording: dict) -> SessionEnvelope:  # type: ignore[type-arg]
    s = recording["session"]
    return SessionEnvelope(
        session_id=str(s["session_id"]),
        platform="mock",
        start_wall_clock=str(s["start_wall_clock"]),
        expected_duration_min=int(s.get("expected_duration_min", 30)),
        expected_participants=list(s.get("expected_participants", [])),
        ground_truth_candidate_id=s.get("ground_truth_candidate_id"),
    )


async def _replay(recording_path: Path, weights: WeightTable) -> tuple[dict, list[Verdict]]:  # type: ignore[type-arg]
    raw = json.loads(recording_path.read_text())
    adapter = MockAdapter(recording_path, sleep_fn=_no_sleep)
    analyzers = build_default(weights, ScriptedLLMProvider())
    verdicts = await run_session(
        adapter=adapter,
        session_envelope=_make_envelope(raw),
        platform="mock",
        analyzers=analyzers,
        weights=weights,
        clock=ManualClock(),
    )
    return raw, verdicts


def _with_weight(base: WeightTable, feature: str, value: float) -> WeightTable:
    """Return a new WeightTable with ``feature`` set to ``value`` (clamped to [0,1])."""
    new_weights = dict(base.weights)
    new_weights[feature] = round(max(0.0, min(1.0, value)), 6)
    return base.model_copy(update={"weights": new_weights})


# ---------------------------------------------------------------------------
# Public API (also imported by tests)
# ---------------------------------------------------------------------------


async def evaluate(weights: WeightTable, recording_paths: list[Path]) -> float:
    """Score = p@1_mean \u2212 0.001\u00d7flips_mean + 0.0001\u00d7(600 \u2212 t2d_mean).

    Maps to docs/ACCURACY_METRICS.md \u00a76.2 ``evaluate``.
    """
    if not recording_paths:
        return 0.0
    pa1_vals: list[float] = []
    flip_vals: list[int] = []
    ttd_vals: list[float] = []
    for path in recording_paths:
        raw, verdicts = await _replay(path, weights)
        gt = raw["session"].get("ground_truth_candidate_id")
        pa1_vals.append(precision_at_1(verdicts, gt))
        flip_vals.append(flips(verdicts))
        t2d = time_to_decision(verdicts)
        ttd_vals.append(t2d if t2d is not None else 600.0)
    pa1_mean = sum(pa1_vals) / len(pa1_vals)
    flips_mean = sum(flip_vals) / len(flip_vals)
    ttd_mean = sum(ttd_vals) / len(ttd_vals)
    return pa1_mean - 0.001 * flips_mean + 0.0001 * (600.0 - ttd_mean)


async def tune(
    recording_paths: list[Path],
    initial_weights: WeightTable,
    *,
    iterations: int = 10,
    vision_recording_count: int = 0,
) -> tuple[WeightTable, list[dict]]:  # type: ignore[type-arg]
    """Coordinate descent over the weight table.

    Only improves weights (never moves to a worse score), so the returned
    score is always \u2265 the initial score (monotonic).
    """
    weights = initial_weights
    history: list[dict] = []  # type: ignore[type-arg]

    for iteration in range(iterations):
        for feature in list(weights.weights.keys()):
            # Hard rule \u00a76.5: vision-guarded features stay 0 without \u22655 recordings
            if feature in _VISION_GUARDED and vision_recording_count < 5:
                continue

            best_score = await evaluate(weights, recording_paths)
            best_val = weights.weights[feature]

            for delta in _COORD_DELTAS:
                candidate_val = weights.weights[feature] + delta
                candidate_weights = _with_weight(weights, feature, candidate_val)
                score = await evaluate(candidate_weights, recording_paths)
                if score > best_score:
                    best_score = score
                    best_val = max(0.0, min(1.0, candidate_val))

            weights = _with_weight(weights, feature, best_val)

        final_iter_score = await evaluate(weights, recording_paths)
        history.append(
            {
                "iteration": iteration,
                "weights": dict(weights.weights),
                "score": final_iter_score,
            }
        )

    return weights, history


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


async def _main(recordings_dir: Path, iterations: int) -> None:
    initial_weights = load_weights()
    paths = sorted(p for p in recordings_dir.glob("*.json") if p.name != ".gitkeep")
    labeled = [
        p
        for p in paths
        if json.loads(p.read_text())["session"].get("ground_truth_candidate_id")
    ]

    if not labeled:
        print("No labeled recordings found; nothing to tune.")
        return

    # Baseline check: p@1 must be \u22650.7 before tuning (\u00a76.5)
    pa1_initial = 0.0
    for p in labeled:
        raw, verdicts = await _replay(p, initial_weights)
        gt = raw["session"].get("ground_truth_candidate_id")
        pa1_initial += precision_at_1(verdicts, gt)
    pa1_initial /= len(labeled)

    if pa1_initial < 0.7:
        raise RuntimeError(
            f"baseline too low; check analyzers (p@1={pa1_initial:.2f} < 0.7)"
        )

    initial_score = await evaluate(initial_weights, labeled)
    print(
        f"Initial score: {initial_score:.4f}  "
        f"(p@1={pa1_initial:.2f}  on {len(labeled)} labeled recordings)"
    )

    # Conservative: no vision recordings detected from file content
    vision_count = 0

    tuned_weights, history = await tune(
        labeled,
        initial_weights,
        iterations=iterations,
        vision_recording_count=vision_count,
    )

    final_score = await evaluate(tuned_weights, labeled)
    print(f"Tuned  score: {final_score:.4f}")

    # --- Write outputs ---
    out_dir = recordings_dir.parent / "weights"
    out_dir.mkdir(exist_ok=True)

    weights_out = {
        "version": "1.1.0",
        "fusion_engine": tuned_weights.fusion_engine,
        "threshold": tuned_weights.threshold,
        "margin": tuned_weights.margin,
        "decay": tuned_weights.decay.model_dump(),
        "weights": tuned_weights.weights,
    }
    weights_path = out_dir / "weights.v1.1.json"
    weights_path.write_text(json.dumps(weights_out, indent=2))
    print(f"Tuned weights written to {weights_path}")

    report_lines = [
        "# Tuning Report v1.1\n",
        f"Initial score: {initial_score:.4f}",
        f"Final   score: {final_score:.4f}",
        f"Recordings:    {len(labeled)}",
        f"Iterations:    {iterations}",
        "",
        "## Weight delta",
        "",
        "| Feature | v1.0 | v1.1 | delta |",
        "|---|---|---|---|",
    ]
    for feature in initial_weights.weights:
        v0 = initial_weights.weights[feature]
        v1 = tuned_weights.weights.get(feature, v0)
        report_lines.append(f"| {feature} | {v0:.4f} | {v1:.4f} | {v1 - v0:+.4f} |")

    report_path = out_dir / "tuning_report.v1.1.md"
    report_path.write_text("\n".join(report_lines))
    print(f"Tuning report written to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tune weights via coordinate descent")
    parser.add_argument(
        "--recordings",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "recordings",
    )
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(_main(args.recordings, args.iterations))
