import { useEffect, useState } from "react";
import { getEvalScenario, type EvalScenarioId } from "./eval-fixtures";
import type { LiveDebugSnapshot, SessionUpdateMessage, Verdict } from "./types";

// Single source of truth for consuming the verdict WebSocket (per AGENTS.md §2.2).

export interface ConfidencePoint {
  ts: number;
  [participantId: string]: number;
}

export type ConnectionState = "connecting" | "open" | "closed";

export interface UseVerdictStreamResult {
  verdict: Verdict | null;
  liveDebug: LiveDebugSnapshot | null;
  history: ConfidencePoint[];
  connectionState: ConnectionState;
}

export interface UseVerdictStreamOptions {
  wsUrl?: string;
  mode?: "live" | "eval";
  evalScenario?: EvalScenarioId;
}

const MAX_HISTORY_POINTS = 500;

function pointFromVerdict(data: Verdict): ConfidencePoint {
  const point: ConfidencePoint = { ts: data.ts };
  if (data.candidate_id !== null && data.confidence !== null) {
    point[data.candidate_id] = data.confidence;
  }
  for (const rejected of data.rejected_hypotheses) {
    point[rejected.participant_id] = rejected.confidence;
  }
  if (
    data.runner_up_id !== null &&
    data.runner_up_confidence !== null &&
    !(data.runner_up_id in point)
  ) {
    point[data.runner_up_id] = data.runner_up_confidence;
  }
  return point;
}

function isVerdict(val: Verdict | SessionUpdateMessage | null): val is Verdict {
  return val !== null && !("kind" in val);
}

export function useVerdictStream(sessionId: string, wsUrl?: string): UseVerdictStreamResult {
  return useVerdictStreamWithOptions(sessionId, { wsUrl });
}

export function useVerdictStreamWithOptions(
  sessionId: string,
  options: UseVerdictStreamOptions = {}
): UseVerdictStreamResult {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [liveDebug, setLiveDebug] = useState<LiveDebugSnapshot | null>(null);
  const [history, setHistory] = useState<ConfidencePoint[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");

  useEffect(() => {
    if (options.mode === "eval") {
      const scenario = getEvalScenario(options.evalScenario);
      setVerdict(scenario.verdict);
      setLiveDebug(scenario.liveDebug);
      setHistory(scenario.history);
      setConnectionState("open");
      return undefined;
    }

    const baseUrl =
      options.wsUrl ??
      `${import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000"}/sessions/${sessionId}/stream`;
    const socket = new WebSocket(baseUrl);
    setConnectionState("connecting");

    socket.onopen = () => setConnectionState("open");
    socket.onclose = () => setConnectionState("closed");
    socket.onerror = () => setConnectionState("closed");
    socket.onmessage = (event: MessageEvent<string>) => {
      const parsed = JSON.parse(event.data) as SessionUpdateMessage | Verdict;
      const isSessionUpdate = "kind" in parsed && parsed.kind === "session_update";
      const data = isSessionUpdate ? parsed.verdict : parsed;
      const live = isSessionUpdate ? parsed.live_debug : null;

      // Type-safe state updates
      if (isVerdict(data)) {
        setVerdict(data);
        setHistory((prev) => {
          const next = [...prev, pointFromVerdict(data)];
          return next.length > MAX_HISTORY_POINTS
            ? next.slice(next.length - MAX_HISTORY_POINTS)
            : next;
        });
      } else {
        setVerdict(null);
      }
      setLiveDebug(live);
    };

    return () => {
      socket.close();
    };
  }, [options.evalScenario, options.mode, options.wsUrl, sessionId]);

  return { verdict, liveDebug, history, connectionState };
}
