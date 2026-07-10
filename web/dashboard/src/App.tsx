import { useState } from "react";
import { getEvalScenario, type EvalScenarioId } from "./eval-fixtures";
import { ParticipantsPanel } from "./components/ParticipantsPanel";
import { ReasonPanel } from "./components/ReasonPanel";
import { SignalHealthPanel } from "./components/SignalHealthPanel";
import { TimelineChart } from "./components/TimelineChart";
import { VerdictCard } from "./components/VerdictCard";
import { StartSessionPanel } from "./components/StartSessionPanel";
import { TranscriptPanel } from "./components/TranscriptPanel";
import { EvalDashboardPanel } from "./components/EvalDashboardPanel";
import { SessionLogsModal } from "./components/SessionLogsModal";
import { useVerdictStreamWithOptions } from "./useVerdictStream";

function dashboardOptionsFromLocation(): {
  sessionId: string;
  mode: "live" | "eval";
  evalScenario: EvalScenarioId;
} {
  const params = new URLSearchParams(window.location.search);
  const mode = params.get("mode") === "eval" ? "eval" : "live";
  const evalScenarioParam = params.get("scenario");
  const evalScenario =
    evalScenarioParam === "renamed_candidate" ||
    evalScenarioParam === "ambiguous" ||
    evalScenarioParam === "happy_path"
      ? evalScenarioParam
      : "happy_path";

  return {
    sessionId: params.get("session") ?? "mock-sess-001",
    mode,
    evalScenario,
  };
}

export default function App() {
  const { sessionId: initialSessionId, mode, evalScenario } = dashboardOptionsFromLocation();
  const [sessionId, setSessionId] = useState(initialSessionId);
  const { verdict, liveDebug, history, connectionState } = useVerdictStreamWithOptions(sessionId, {
    mode,
    evalScenario,
  });
  const evalMeta = mode === "eval" ? getEvalScenario(evalScenario) : null;

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(251,191,36,0.18),_transparent_30%),linear-gradient(180deg,_#f7f4ef_0%,_#f3efe7_48%,_#ebe5db_100%)] text-stone-900">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <section className="rounded-[36px] border border-stone-200 bg-white/80 p-6 shadow-[0_24px_80px_rgba(41,37,36,0.08)] backdrop-blur">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-stone-500">
                Candidate Identification System
              </p>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-stone-900 sm:text-4xl">
                Continuous candidate identification with confidence, ambiguity handling, and evidence.
              </h1>
              <p className="mt-3 text-sm leading-6 text-stone-600 sm:text-base">
                The prototype continuously ranks participants, explains why the top participant is leading,
                and stays undecided when names, transcript, or behavioral signals remain ambiguous.
              </p>
            </div>
            <div className="flex flex-col items-end gap-3">
              <div className="rounded-[28px] border border-stone-200 bg-stone-50/80 px-4 py-3 text-sm text-stone-600">
                <p className="font-medium text-stone-900">Session {sessionId}</p>
                <p className="mt-1">connection: {connectionState}</p>
                <p className="mt-1">
                  mode: {mode}
                  {mode === "eval" && evalMeta ? ` · ${evalMeta.label}` : ""}
                </p>
              </div>
              <SessionLogsModal
                currentSessionId={sessionId}
                onSelectSession={(newId) => setSessionId(newId)}
                liveDebug={liveDebug}
              />
            </div>
          </div>
          {evalMeta && (
            <div className="mt-5 rounded-[28px] border border-amber-200 bg-amber-50/85 px-4 py-3 text-sm text-amber-900">
              <p className="font-medium">Evaluation mode</p>
              <p className="mt-1">{evalMeta.description}</p>
            </div>
          )}
        </section>

        <div className="mt-6 space-y-6">
          <StartSessionPanel
            currentSessionId={sessionId}
            onSessionChanged={(newId) => setSessionId(newId)}
          />
          <EvalDashboardPanel verdict={verdict} evalScenario={evalScenario} />
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-[1.45fr_0.95fr]">
          <div className="space-y-6">
            <VerdictCard verdict={verdict} />
            <TranscriptPanel sessionId={sessionId} liveDebug={liveDebug} />
            <TimelineChart history={history} />
            <ReasonPanel verdict={verdict} />
          </div>
          <div className="space-y-6">
            <ParticipantsPanel verdict={verdict} liveDebug={liveDebug} history={history} />
            <SignalHealthPanel liveDebug={liveDebug} />
            {liveDebug && (
              <section className="rounded-[28px] border border-stone-200 bg-white/85 p-5 shadow-sm">
                <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
                  Live Debug
                </h2>
                <div className="mt-4 grid gap-3 text-sm text-stone-600">
                  <p>control messages: {liveDebug.control_messages}</p>
                  <p>audio chunks: {liveDebug.audio_chunks}</p>
                  <p>transcript segments: {liveDebug.transcript_segments}</p>
                  <p>last control: {liveDebug.last_control_type ?? "none"}</p>
                </div>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
