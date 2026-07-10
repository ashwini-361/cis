import type { LiveDebugSnapshot } from "../types";

function formatCoverage(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function readinessTone(ready: boolean): string {
  return ready ? "text-emerald-700" : "text-amber-700";
}

export function SignalHealthPanel({ liveDebug }: { liveDebug: LiveDebugSnapshot | null }) {
  if (!liveDebug) {
    return null;
  }

  const items = [
    {
      label: "Transcript",
      value: liveDebug.transcript_source_active ? "active" : "missing",
      detail: `${liveDebug.transcript_segments} captured segments`,
      ready: liveDebug.transcript_source_active,
    },
    {
      label: "Audio mapping",
      value: formatCoverage(liveDebug.audio_mapping_coverage),
      detail: liveDebug.per_participant_mode ? "per-participant mode" : "fallback mode",
      ready: liveDebug.audio_mapping_coverage >= 0.8,
    },
    {
      label: "Extension",
      value: liveDebug.extension_connected ? "connected" : "offline",
      detail: `${liveDebug.extension_connections} connection(s)`,
      ready: liveDebug.extension_connected,
    },
    {
      label: "Lag",
      value: liveDebug.transcribing_lag ? "behind" : "healthy",
      detail: liveDebug.transcribing_lag ? "transcript is trailing audio" : "audio and transcript are aligned",
      ready: !liveDebug.transcribing_lag,
    },
  ];

  return (
    <section className="rounded-[28px] border border-stone-200 bg-white/85 p-5 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
        Signal Health
      </h2>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {items.map((item) => (
          <div key={item.label} className="rounded-2xl border border-stone-200 bg-stone-50/80 p-3">
            <p className="text-xs uppercase tracking-[0.14em] text-stone-500">{item.label}</p>
            <p className={`mt-2 text-lg font-semibold ${readinessTone(item.ready)}`}>{item.value}</p>
            <p className="mt-1 text-sm text-stone-500">{item.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
