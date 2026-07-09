import { useEffect, useState } from "react";
import type { Verdict } from "./types";

// Single source of truth for consuming the verdict WebSocket (per AGENTS.md §2.2).

export interface ConfidencePoint {
  ts: number;
  [participantId: string]: number;
}

export type ConnectionState = "connecting" | "open" | "closed";

export interface UseVerdictStreamResult {
  verdict: Verdict | null;
  history: ConfidencePoint[];
  connectionState: ConnectionState;
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

export function useVerdictStream(sessionId: string, wsUrl?: string): UseVerdictStreamResult {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [history, setHistory] = useState<ConfidencePoint[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");

  useEffect(() => {
    const url = wsUrl ?? `ws://${window.location.hostname}:3000/sessions/${sessionId}/stream`;
    const socket = new WebSocket(url);
    setConnectionState("connecting");

    socket.onopen = () => setConnectionState("open");
    socket.onclose = () => setConnectionState("closed");
    socket.onerror = () => setConnectionState("closed");
    socket.onmessage = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as Verdict;
      setVerdict(data);
      setHistory((prev) => {
        const next = [...prev, pointFromVerdict(data)];
        return next.length > MAX_HISTORY_POINTS
          ? next.slice(next.length - MAX_HISTORY_POINTS)
          : next;
      });
    };

    return () => {
      socket.close();
    };
  }, [sessionId, wsUrl]);

  return { verdict, history, connectionState };
}
