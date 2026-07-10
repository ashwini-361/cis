import type { ConfidencePoint } from "../useVerdictStream";
import type { LiveDebugSnapshot, Verdict } from "../types";

interface ParticipantRow {
  participantId: string;
  displayName: string;
  confidence: number;
  role: string;
  status: string;
}

function participantRows(
  verdict: Verdict | null,
  liveDebug: LiveDebugSnapshot | null,
  history: ConfidencePoint[]
): ParticipantRow[] {
  const latestPoint = history[history.length - 1];
  const latestScores = new Map<string, number>();

  if (latestPoint) {
    Object.entries(latestPoint).forEach(([key, value]) => {
      if (key !== "ts" && typeof value === "number") {
        latestScores.set(key, value);
      }
    });
  }

  const roleRows = liveDebug?.role_summary?.roles ?? [];
  const rows = new Map<string, ParticipantRow>();

  roleRows.forEach((entry) => {
    const confidence = latestScores.get(entry.participant_id) ?? entry.confidence;
    rows.set(entry.participant_id, {
      participantId: entry.participant_id,
      displayName: entry.display_name,
      confidence,
      role: entry.role,
      status: "observed",
    });
  });

  if (verdict?.candidate_id && verdict.candidate_name) {
    rows.set(verdict.candidate_id, {
      participantId: verdict.candidate_id,
      displayName: verdict.candidate_name,
      confidence: verdict.confidence ?? latestScores.get(verdict.candidate_id) ?? 0,
      role: verdict.is_decision ? "candidate" : "leading",
      status: verdict.is_decision ? "selected" : "leading",
    });
  }

  verdict?.rejected_hypotheses.forEach((item) => {
    const existing = rows.get(item.participant_id);
    rows.set(item.participant_id, {
      participantId: item.participant_id,
      displayName: existing?.displayName ?? item.display_name,
      confidence: latestScores.get(item.participant_id) ?? item.confidence,
      role: existing?.role ?? "observer",
      status: existing?.status ?? "considered",
    });
  });

  if (
    verdict?.runner_up_id &&
    !rows.has(verdict.runner_up_id) &&
    verdict.runner_up_confidence !== null
  ) {
    rows.set(verdict.runner_up_id, {
      participantId: verdict.runner_up_id,
      displayName: verdict.runner_up_id,
      confidence: verdict.runner_up_confidence,
      role: "runner-up",
      status: "considered",
    });
  }

  return [...rows.values()].sort((a, b) => b.confidence - a.confidence);
}

function statusTone(status: string): string {
  if (status === "selected") return "bg-emerald-100 text-emerald-800";
  if (status === "leading") return "bg-amber-100 text-amber-800";
  return "bg-slate-100 text-slate-700";
}

export function ParticipantsPanel({
  verdict,
  liveDebug,
  history,
}: {
  verdict: Verdict | null;
  liveDebug: LiveDebugSnapshot | null;
  history: ConfidencePoint[];
}) {
  const rows = participantRows(verdict, liveDebug, history);

  if (rows.length === 0) {
    return (
      <section className="rounded-[28px] border border-stone-200 bg-white/85 p-5 shadow-sm">
        <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
          Participants
        </h2>
        <p className="mt-3 text-sm text-stone-500">Waiting for participants to appear.</p>
      </section>
    );
  }

  return (
    <section
      className="rounded-[28px] border border-stone-200 bg-white/85 p-5 shadow-sm"
      data-testid="participants-panel"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
          Participants
        </h2>
        <span className="text-xs text-stone-400">{rows.length} tracked</span>
      </div>
      <div className="mt-4 space-y-3">
        {rows.map((row) => {
          const confidencePct = Math.round(row.confidence * 100);
          return (
            <div key={row.participantId} className="rounded-2xl border border-stone-200 bg-stone-50/80 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium text-stone-900">{row.displayName}</p>
                  <p className="text-xs text-stone-500">
                    {row.role} · {row.participantId}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${statusTone(row.status)}`}>
                  {row.status}
                </span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-stone-200">
                <div
                  className="h-full rounded-full bg-stone-900 transition-all duration-500"
                  style={{ width: `${confidencePct}%` }}
                />
              </div>
              <p className="mt-2 text-sm text-stone-600">{confidencePct}% confidence</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
