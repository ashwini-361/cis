import type { Verdict } from "../types";

export function ReasonPanel({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) {
    return null;
  }

  return (
    <div
      className="rounded-[28px] border border-stone-200 bg-white/85 p-5 shadow-sm"
      data-testid="reason-panel"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
          Explanation
        </h3>
        <span className="text-xs text-stone-400">
          {verdict.is_decision ? "selected participant" : "why we are waiting"}
        </span>
      </div>
      <ul className="mt-4 space-y-2">
        {verdict.reasons.map((reason) => (
          <li
            key={reason}
            className="animate-fadeIn rounded-2xl border border-stone-200 bg-stone-50/80 px-3 py-2 text-sm text-stone-700"
          >
            {reason}
          </li>
        ))}
      </ul>

      {verdict.rejected_hypotheses.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-semibold text-stone-500">Rejected hypotheses</h4>
          {verdict.rejected_hypotheses.map((rejected) => (
            <div
              key={rejected.participant_id}
              className="mt-2 rounded-2xl border border-stone-200 bg-stone-50/80 p-3 text-sm text-stone-600"
            >
              <p className="font-medium text-stone-800">
                {rejected.display_name} ({Math.round(rejected.confidence * 100)}%)
              </p>
              <ul className="mt-2 space-y-1">
                {rejected.top_negative_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
