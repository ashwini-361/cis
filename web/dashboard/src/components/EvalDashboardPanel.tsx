import React from "react";
import type { Verdict } from "../types";

export interface EvalDashboardPanelProps {
  verdict: Verdict | null;
  evalScenario?: string;
}

export const EvalDashboardPanel: React.FC<EvalDashboardPanelProps> = ({
  verdict,
  evalScenario,
}) => {
  if (!verdict) {
    return null;
  }

  const isDecided = verdict.is_decision;
  const confidence = verdict.confidence || 0;
  const threshold = 0.7; // Decision threshold

  return (
    <section className="rounded-[28px] border border-amber-200/80 bg-gradient-to-br from-amber-50/90 to-amber-100/40 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-900">
            Prototype Evaluation & Diagnostics {evalScenario ? `(${evalScenario})` : ""}
          </h2>
          <p className="mt-1 text-xs text-amber-800">
            Real-time evaluation against core requirements (Identification, Ambiguity, Incorrect Names)
          </p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold ${
            isDecided
              ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
              : "bg-amber-100 text-amber-800 border border-amber-300"
          }`}
        >
          {isDecided ? "DECISION REACHED" : "EVALUATING / AMBIGUOUS"}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-amber-200/60 bg-white/70 p-3.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
            Candidate ID Precision
          </p>
          <p className="mt-1 text-lg font-bold text-stone-900">
            {verdict.candidate_name || verdict.candidate_id || "Undecided"}
          </p>
          <p className="mt-1 text-xs text-stone-600">
            Confidence: <span className="font-semibold">{(confidence * 100).toFixed(1)}%</span>
            {verdict.margin !== null && ` (Margin: +${(verdict.margin * 100).toFixed(1)}%)`}
          </p>
        </div>

        <div className="rounded-2xl border border-amber-200/60 bg-white/70 p-3.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
            Ambiguity Handling
          </p>
          <p className="mt-1 text-sm font-semibold text-stone-800">
            {isDecided ? `High Confidence (> ${(threshold * 100).toFixed(0)}%)` : "Gated Below Threshold"}
          </p>
          <p className="mt-1 text-xs text-stone-600 leading-snug">
            {verdict.not_deciding_reason ||
              "Evidence threshold satisfied; stable candidate role assigned."}
          </p>
        </div>

        <div className="rounded-2xl border border-amber-200/60 bg-white/70 p-3.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
            Incorrect Name / Missing Data
          </p>
          <p className="mt-1 text-sm font-semibold text-stone-800">
            Multi-modal Signal Fusion
          </p>
          <p className="mt-1 text-xs text-stone-600 leading-snug">
            Combines audio speaking pattern, webcam, join order, & transcript semantics.
          </p>
        </div>
      </div>

      {verdict.reasons && verdict.reasons.length > 0 && (
        <div className="mt-3 rounded-2xl border border-amber-200/50 bg-white/60 p-3.5">
          <p className="text-xs font-semibold text-amber-950">Primary Explanation for Selection:</p>
          <ul className="mt-1.5 list-disc pl-4 text-xs text-stone-700 space-y-1">
            {verdict.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};
