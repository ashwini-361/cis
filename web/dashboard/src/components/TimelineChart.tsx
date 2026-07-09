import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ConfidencePoint } from "../useVerdictStream";

const COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#d97706"];

export function TimelineChart({ history }: { history: ConfidencePoint[] }) {
  if (history.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 p-4 text-sm text-gray-500">
        No data yet
      </div>
    );
  }

  const participantIds = Array.from(
    new Set(history.flatMap((point) => Object.keys(point).filter((key) => key !== "ts")))
  );

  return (
    <div className="rounded-lg border border-gray-200 p-4" style={{ height: 240 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={history}>
          <XAxis dataKey="ts" />
          <YAxis domain={[0, 1]} />
          <Tooltip />
          {participantIds.map((id, i) => (
            <Line
              key={id}
              type="monotone"
              dataKey={id}
              stroke={COLORS[i % COLORS.length]}
              dot={false}
              isAnimationActive
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
