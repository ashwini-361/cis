import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ConfidencePoint } from "../useVerdictStream";

const COLORS = ["#0f766e", "#b45309", "#7c3aed", "#2563eb", "#dc2626"];

export function TimelineChart({ history }: { history: ConfidencePoint[] }) {
  if (history.length === 0) {
    return (
      <div className="rounded-[28px] border border-stone-200 bg-white/85 p-5 text-sm text-stone-500 shadow-sm">
        No data yet
      </div>
    );
  }

  const participantIds = Array.from(
    new Set(history.flatMap((point) => Object.keys(point).filter((key) => key !== "ts")))
  );

  return (
    <div className="rounded-[28px] border border-stone-200 bg-white/85 p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
            Confidence Timeline
          </h2>
          <p className="mt-1 text-sm text-stone-500">
            Continuous confidence updates across tracked participants
          </p>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-stone-500">
          {participantIds.map((id, i) => (
            <span key={id} className="inline-flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: COLORS[i % COLORS.length] }}
              />
              {id}
            </span>
          ))}
        </div>
      </div>
      <div style={{ height: 240 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history}>
            <XAxis dataKey="ts" tick={{ fill: "#78716c", fontSize: 12 }} />
            <YAxis domain={[0, 1]} tick={{ fill: "#78716c", fontSize: 12 }} />
            <Tooltip />
            {participantIds.map((id, i) => (
              <Line
                key={id}
                type="monotone"
                dataKey={id}
                stroke={COLORS[i % COLORS.length]}
                dot={false}
                isAnimationActive
                strokeWidth={2.5}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
