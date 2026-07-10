import React, { useEffect, useState } from "react";
import type { LiveDebugSnapshot } from "../types";

export interface SessionInfo {
  session_id: string;
  verdict_count?: number;
  latest_candidate_name?: string | null;
  latest_confidence?: number | null;
}

export interface SessionLogsModalProps {
  currentSessionId: string;
  onSelectSession: (sessionId: string) => void;
  liveDebug: LiveDebugSnapshot | null;
  apiBaseUrl?: string;
}

export const SessionLogsModal: React.FC<SessionLogsModalProps> = ({
  currentSessionId,
  onSelectSession,
  liveDebug,
  apiBaseUrl = "http://localhost:8000",
}) => {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"logs" | "sessions">("logs");

  useEffect(() => {
    if (!isOpen) return;
    const fetchSessions = async () => {
      try {
        const res = await fetch(`${apiBaseUrl}/sessions`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data.sessions)) {
            setSessions(data.sessions);
          }
        }
      } catch {
        // network catch
      }
    };
    fetchSessions();
  }, [isOpen, apiBaseUrl]);

  const recentEvents = liveDebug?.recent_events ?? [];

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="rounded-full border border-stone-300 bg-white/80 px-4 py-1.5 text-xs font-semibold text-stone-700 shadow-sm hover:bg-stone-100 transition"
      >
        View All Session Logs & Sessions
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 backdrop-blur-sm p-4">
          <div className="flex h-[80vh] w-full max-w-5xl flex-col rounded-[28px] border border-stone-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-stone-200 px-6 py-4">
              <div className="flex items-center gap-4">
                <h3 className="text-base font-semibold text-stone-900">
                  Session Logs & Active Sessions
                </h3>
                <div className="flex rounded-xl bg-stone-100 p-1 text-xs font-medium">
                  <button
                    type="button"
                    onClick={() => setActiveTab("logs")}
                    className={`rounded-lg px-3 py-1 transition ${
                      activeTab === "logs" ? "bg-white text-stone-900 shadow-sm" : "text-stone-600"
                    }`}
                  >
                    Event Logs ({recentEvents.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("sessions")}
                    className={`rounded-lg px-3 py-1 transition ${
                      activeTab === "sessions" ? "bg-white text-stone-900 shadow-sm" : "text-stone-600"
                    }`}
                  >
                    All Sessions ({sessions.length})
                  </button>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-full p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 text-sm">
              {activeTab === "logs" ? (
                recentEvents.length === 0 ? (
                  <p className="py-12 text-center text-xs italic text-stone-400">
                    No runtime event logs recorded for session {currentSessionId} yet.
                  </p>
                ) : (
                  <div className="space-y-3">
                    {recentEvents.map((ev, idx) => (
                      <div
                        key={idx}
                        className="rounded-xl border border-stone-100 bg-stone-50/70 p-3 font-mono text-xs"
                      >
                        <div className="flex items-center justify-between font-sans">
                          <span className="font-semibold uppercase tracking-wider text-amber-700">
                            {ev.kind}
                          </span>
                          <span className="text-stone-400">{new Date(ev.ts * 1000).toLocaleTimeString()}</span>
                        </div>
                        <p className="mt-1 font-sans font-medium text-stone-800">{ev.message}</p>
                        {ev.payload && Object.keys(ev.payload).length > 0 && (
                          <pre className="mt-2 overflow-x-auto rounded-lg bg-stone-200/60 p-2 text-[11px] text-stone-700">
                            {JSON.stringify(ev.payload, null, 2)}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <div className="grid gap-4 sm:grid-cols-2">
                  {sessions.map((sess) => (
                    <div
                      key={sess.session_id}
                      className={`flex flex-col justify-between rounded-2xl border p-4 transition ${
                        sess.session_id === currentSessionId
                          ? "border-amber-500 bg-amber-50/40"
                          : "border-stone-200 bg-white hover:border-stone-300"
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-stone-900">{sess.session_id}</span>
                          {sess.session_id === currentSessionId && (
                            <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-[10px] font-semibold text-amber-800">
                              Active
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-stone-500">
                          Verdicts: {sess.verdict_count ?? 0}
                        </p>
                        {sess.latest_candidate_name && (
                          <p className="mt-1 text-xs text-stone-700">
                            Leading: <span className="font-medium">{sess.latest_candidate_name}</span> (
                            {((sess.latest_confidence ?? 0) * 100).toFixed(0)}%)
                          </p>
                        )}
                      </div>
                      <div className="mt-4 flex justify-end">
                        <button
                          type="button"
                          onClick={() => {
                            onSelectSession(sess.session_id);
                            setIsOpen(false);
                          }}
                          className="rounded-xl border border-stone-300 bg-stone-50 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-100 transition"
                        >
                          Switch to Session
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
};
