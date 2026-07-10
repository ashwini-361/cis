#!/usr/bin/env python
"""scripts/run_accuracy.py \u2014 offline accuracy harness.

Drives every labeled recording in data/recordings/ through the real runtime
(MockAdapter + ManualClock + ScriptedLLMProvider) and prints a markdown
table of precision@1, time-to-decision, and flip counts.

Asserts each scenario against its ``expected_output`` block so the harness
doubles as a contract test when run in CI.

Usage:
    uv run python scripts/run_accuracy.py [--recordings PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Ensure the project root is on sys.path when invoked as a standalone script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import load_weights  # noqa: E402
from app.harness.metrics import (  # noqa: E402
    ScenarioReport,
    flips,
    precision_at_1,
    precision_at_1_at_decision,
    summarize,
    time_to_decision,
)
from app.harness.scripted_llm import ScriptedLLMProvider  # noqa: E402
from app.ingest.mock import MockAdapter  # noqa: E402
from app.runtime.clock import ManualClock  # noqa: E402
from app.runtime.registry import build_default  # noqa: E402
from app.runtime.session_runner import run_session  # noqa: E402
from app.schema import SessionEnvelope, Verdict, WeightTable  # noqa: E402


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


async def replay(recording_path: Path, weights: WeightTable) -> tuple[Any, list[Verdict]]:
    """Replay a single recording; return (raw_dict, verdicts)."""
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


def build_report(raw: dict, verdicts: list[Verdict]) -> ScenarioReport:  # type: ignore[type-arg]
    gt = raw["session"].get("ground_truth_candidate_id")
    first_dec = next((v for v in verdicts if v.is_decision), None)
    return ScenarioReport(
        scenario_id=raw.get("scenario_id", "unknown"),
        ground_truth_id=gt,
        final_candidate_id=verdicts[-1].candidate_id if verdicts else None,
        precision_at_1=precision_at_1(verdicts, gt),
        precision_at_1_at_decision=precision_at_1_at_decision(verdicts, gt),
        time_to_decision=time_to_decision(verdicts),
        flips=flips(verdicts),
        runner_up_confidence=first_dec.runner_up_confidence if first_dec else None,
    )


def assert_vs_expected(report: ScenarioReport, expected: dict) -> None:  # type: ignore[type-arg]
    """Raise AssertionError if the report violates the recording's expected_output."""
    errs: list[str] = []
    if expected.get("is_decision") and report.time_to_decision is None:
        errs.append("expected a decision but none was emitted")
    exp_cid = expected.get("candidate_id")
    if exp_cid is not None and report.final_candidate_id != exp_cid:
        errs.append(
            f"final candidate_id={report.final_candidate_id!r}, want {exp_cid!r}"
        )
    max_runner_up = expected.get("max_confidence_runner_up")
    if (
        max_runner_up is not None
        and report.runner_up_confidence is not None
        and report.runner_up_confidence > max_runner_up
    ):
        errs.append(
            f"runner_up_confidence={report.runner_up_confidence:.3f} > {max_runner_up}"
        )
    if errs:
        raise AssertionError(f"[{report.scenario_id}] " + "; ".join(errs))


async def _main(recordings_dir: Path) -> None:
    weights = load_weights()
    paths = sorted(p for p in recordings_dir.glob("*.json") if p.name != ".gitkeep")
    if not paths:
        print(f"No recordings found in {recordings_dir}")
        return

    reports: list[ScenarioReport] = []
    for path in paths:
        raw, verdicts = await replay(path, weights)
        report = build_report(raw, verdicts)
        assert_vs_expected(report, raw.get("expected_output", {}))
        reports.append(report)
        t2d_str = (
            f"{report.time_to_decision:.0f}s"
            if report.time_to_decision is not None
            else "\u2014"
        )
        print(
            f"  [{report.scenario_id}] p@1={report.precision_at_1:.2f}"
            f"  t2d={t2d_str}  flips={report.flips}"
        )

    summary = summarize(reports)

    md_rows = [
        "",
        "| Scenario | p@1 | t2d (s) | flips | runner-up conf |",
        "|---|---|---|---|---|",
    ]
    for r in reports:
        t2d = (
            f"{r.time_to_decision:.0f}" if r.time_to_decision is not None else "\u2014"
        )
        rup = (
            f"{r.runner_up_confidence:.2f}"
            if r.runner_up_confidence is not None
            else "\u2014"
        )
        md_rows.append(
            f"| `{r.scenario_id}` | {r.precision_at_1:.2f} | {t2d} | {r.flips} | {rup} |"
        )
    p50 = (
        f"{summary.time_to_decision_p50:.0f}"
        if summary.time_to_decision_p50 is not None
        else "\u2014"
    )
    p90 = (
        f"{summary.time_to_decision_p90:.0f}"
        if summary.time_to_decision_p90 is not None
        else "\u2014"
    )
    md_rows.append(
        f"| **dataset** | **{summary.precision_at_1:.2f}** |"
        f" **p50={p50} / p90={p90}** | **mean={summary.flips_mean:.1f}** | |"
    )
    md_rows.append("")
    print("\n".join(md_rows))

    out_dir = recordings_dir.parent / "weights"
    out_dir.mkdir(exist_ok=True)
    md_path = out_dir / "accuracy_report.v1.0.md"
    json_path = out_dir / "accuracy_report.v1.0.json"

    md_path.write_text("# Accuracy Report v1.0\n\n" + "\n".join(md_rows[1:]))
    json_report = {
        "version": "1.0",
        "precision_at_1": summary.precision_at_1,
        "time_to_decision_p50": summary.time_to_decision_p50,
        "time_to_decision_p90": summary.time_to_decision_p90,
        "flips_mean": summary.flips_mean,
        "scenarios": [
            {
                "scenario_id": r.scenario_id,
                "precision_at_1": r.precision_at_1,
                "time_to_decision": r.time_to_decision,
                "flips": r.flips,
                "runner_up_confidence": r.runner_up_confidence,
            }
            for r in reports
        ],
    }
    json_path.write_text(json.dumps(json_report, indent=2))
    print(f"Reports written to {md_path} and {json_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run accuracy harness over recordings")
    parser.add_argument(
        "--recordings",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "recordings",
    )
    args = parser.parse_args()
    asyncio.run(_main(args.recordings))
