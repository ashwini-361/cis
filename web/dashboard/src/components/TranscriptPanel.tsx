import React, { useEffect, useState } from "react";
import type { LiveDebugSnapshot } from "../types";

export interface TranscriptSegment {
  segment_id: string;
  session_id: string;
  participant_id: string;
  speaker_name: string | null;
  text: string;
  start_sec: number;
  end_sec: number;
  source: string;
  arrival_sequence: number;
}

export interface TranscriptPanelProps {
  sessionId: string;
  liveDebug: LiveDebugSnapshot | null;
  apiBaseUrl?: string;
}

export const TranscriptPanel: React.FC<TranscriptPanelProps> = ({
  sessionId,
  liveDebug,
  apiBaseUrl = "http://localhost:8000",
}) => {
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    const fetchTranscript = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}/transcript`);
        if (res.ok && active) {
          const data = await res.json();
          if (Array.isArray(data.segments)) {
            setSegments(data.segments);
          }
        }
      } catch {
        // Silent catch on network error during polling
      } finally {
        if (active) setLoading(false);
      }
    };

    fetchTranscript();
    const interval = setInterval(fetchTranscript, 2500);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [sessionId, apiBaseUrl, liveDebug?.transcript_segments]);

  // Lookup role from liveDebug if available
  const getRoleBadge = (speakerName: string | null, participantId: string) => {
    if (!liveDebug?.role_summary?.roles) return null;
    const match = liveDebug.role_summary.roles.find(
      (r) => r.participant_id === participantId || r.display_name === speakerName
    );
    if (!match) return null;
    const roleColors: Record<string, string> = {
      candidate: "bg-amber-100 text-amber-800 border-amber-200",
      interviewer: "bg-blue-100 text-blue-800 border-blue-200",
      observer: "bg-stone-100 text-stone-700 border-stone-200",
      unclear: "bg-stone-100 text-stone-500 border-stone-200",
    };
    return (
      <span
        className={`ml-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase ${
          roleColors[match.role] || roleColors.unclear
        }`}
      >
        {match.role}
      </span>
    );
  };

  return (
    <section className="rounded-[28px] border border-stone-200 bg-white/90 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
            Live Speaker-Attributed Transcript
          </h2>
          <p className="mt-1 text-xs text-stone-600">
            Real-time transcript feed with speaker display name and role attribution
          </p>
        </div>
        <span className="rounded-full bg-stone-100 px-3 py-1 text-xs font-medium text-stone-600">
          {loading ? "Syncing..." : `${segments.length} segments`}
        </span>
      </div>

      <div className="mt-4 max-h-72 overflow-y-auto space-y-3 pr-1 text-sm">
        {segments.length === 0 ? (
          <p className="py-8 text-center text-xs italic text-stone-400">
            No transcript segments captured yet for session {sessionId}. Active speech or extension captions will appear here automatically.
          </p>
        ) : (
          segments.map((seg) => {
            const displayName = seg.speaker_name || seg.participant_id;
            return (
              <div
                key={seg.segment_id}
                className="rounded-2xl border border-stone-100 bg-stone-50/70 p-3 transition hover:bg-stone-100/60"
              >
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center font-semibold text-stone-800">
                    <span>{displayName}</span>
                    {getRoleBadge(seg.speaker_name, seg.participant_id)}
                  </div>
                  <div className="flex items-center gap-2 text-stone-400">
                    <span className="rounded bg-stone-200/80 px-1.5 py-0.5 text-[10px] uppercase font-mono">
                      {seg.source}
                    </span>
                    <span>{seg.start_sec.toFixed(1)}s</span>
                  </div>
                </div>
                <p className="mt-1.5 text-stone-700 leading-relaxed">{seg.text}</p>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
};
