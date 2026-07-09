import type { Verdict } from "../types";

export function VerdictCard({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) {
    return (
      <div className="rounded-lg border border-gray-200 p-4" data-testid="verdict-card">
        Waiting for verdict…
      </div>
    );
  }

  if (!verdict.is_decision) {
    return (
      <div
        className="rounded-lg border border-yellow-300 bg-yellow-50 p-4"
        data-testid="verdict-card"
      >
        <p className="font-semibold">Still deciding…</p>
        {verdict.not_deciding_reason !== null && (
          <p className="text-sm text-gray-600">{verdict.not_deciding_reason}</p>
        )}
      </div>
    );
  }

  const confidencePct = Math.round((verdict.confidence ?? 0) * 100);

  return (
    <div className="rounded-lg border border-green-300 bg-green-50 p-4" data-testid="verdict-card">
      <p className="font-semibold">Candidate: {verdict.candidate_name}</p>
      <div className="mt-2 h-2 w-full rounded bg-gray-200">
        <div
          className="h-2 rounded bg-green-600 transition-all duration-500"
          style={{ width: `${confidencePct}%` }}
        />
      </div>
      <p className="text-sm text-gray-600">{confidencePct}% confidence</p>
    </div>
  );
}
