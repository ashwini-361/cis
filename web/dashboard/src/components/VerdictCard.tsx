import type { Verdict } from "../types";

export function VerdictCard({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) {
    return (
      <div
        className="rounded-[32px] border border-stone-200 bg-white/85 p-6 shadow-sm"
        data-testid="verdict-card"
      >
        Waiting for verdict…
      </div>
    );
  }

  const confidencePct = Math.round((verdict.confidence ?? 0) * 100);
  const isDecision = verdict.is_decision;
  const title = isDecision ? "Candidate identified" : "Current leader";
  const accent = isDecision
    ? "border-emerald-300 bg-emerald-50/80"
    : "border-amber-300 bg-amber-50/85";
  const bar = isDecision ? "bg-emerald-600" : "bg-amber-500";
  const candidateLabel = verdict.candidate_name ?? verdict.candidate_id ?? "Awaiting candidate";

  return (
    <div className={`rounded-[32px] border p-6 shadow-sm ${accent}`} data-testid="verdict-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-stone-500">{title}</p>
          <p className="mt-2 text-2xl font-semibold text-stone-900">{candidateLabel}</p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${
            isDecision ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
          }`}
        >
          {isDecision ? "decided" : "still deciding"}
        </span>
      </div>
      <div className="mt-5 h-3 w-full overflow-hidden rounded-full bg-white/80">
        <div
          className={`h-3 rounded-full transition-all duration-500 ${bar}`}
          style={{ width: `${confidencePct}%` }}
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-sm text-stone-600">
        <p>{confidencePct}% confidence</p>
        <p>{verdict.analyzer_count} analyzers active</p>
        <p>{verdict.total_evidence} evidence items</p>
      </div>
      {!isDecision && verdict.not_deciding_reason !== null && (
        <p className="mt-4 text-sm text-stone-700">{verdict.not_deciding_reason}</p>
      )}
    </div>
  );
}
