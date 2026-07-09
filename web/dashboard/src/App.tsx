import { VerdictCard } from "./components/VerdictCard";
import { TimelineChart } from "./components/TimelineChart";
import { ReasonPanel } from "./components/ReasonPanel";
import { useVerdictStream } from "./useVerdictStream";

function sessionIdFromLocation(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get("session") ?? "mock-sess-001";
}

export default function App() {
  const sessionId = sessionIdFromLocation();
  const { verdict, history, connectionState } = useVerdictStream(sessionId);

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <h1 className="text-xl font-bold">cis — Session {sessionId}</h1>
      <p className="text-xs text-gray-400">connection: {connectionState}</p>
      <VerdictCard verdict={verdict} />
      <TimelineChart history={history} />
      <ReasonPanel verdict={verdict} />
    </div>
  );
}
