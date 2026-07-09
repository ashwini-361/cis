import type { Verdict } from "../types";

export function ReasonPanel({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) {
    return null;
  }

  return (
    <div className="rounded-lg border border-gray-200 p-4" data-testid="reason-panel">
      <h3 className="mb-2 font-semibold">Why</h3>
      <ul className="space-y-1">
        {verdict.reasons.map((reason) => (
          <li key={reason} className="animate-fadeIn text-sm">
            • {reason}
          </li>
        ))}
      </ul>

      {verdict.rejected_hypotheses.length > 0 && (
        <div className="mt-3">
          <h4 className="text-sm font-semibold text-gray-500">Rejected hypotheses</h4>
          {verdict.rejected_hypotheses.map((rejected) => (
            <div key={rejected.participant_id} className="mt-1 text-sm text-gray-600">
              {rejected.display_name} ({Math.round(rejected.confidence * 100)}%)
              <ul className="ml-4 list-disc">
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
