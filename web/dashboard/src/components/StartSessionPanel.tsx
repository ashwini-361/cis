import React, { useState } from "react";

export interface StartSessionPanelProps {
  currentSessionId: string;
  onSessionChanged: (newSessionId: string) => void;
  apiBaseUrl?: string;
}

export const StartSessionPanel: React.FC<StartSessionPanelProps> = ({
  currentSessionId,
  onSessionChanged,
  apiBaseUrl = "http://localhost:8000",
}) => {
  const [isOpen, setIsOpen] = useState(true);
  const [sessionId, setSessionId] = useState(currentSessionId || "mock-sess-001");
  const [platform, setPlatform] = useState<"meet" | "zoom">("meet");
  const [candidateName, setCandidateName] = useState("vipul Choudhary");
  const [candidateEmail, setCandidateEmail] = useState("vipul.Choudhary@example.com");
  const [interviewerNames, setInterviewerNames] = useState("Ashwini Kumar, Priya Patel");
  const [expectedParticipants, setExpectedParticipants] = useState("Rahul Sharma, Ashwini Kumar, Priya Patel");

  // LLM Configuration fields (mirrors app/main.py _SessionStartBody)
  const [llmBaseUrl, setLlmBaseUrl] = useState("http://localhost:4001");
  const [llmApiKey, setLlmApiKey] = useState("sk-1234");
  const [llmModel, setLlmModel] = useState("deepseek-flash");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const handleStartSession = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccessMsg(null);

    const parseList = (str: string) =>
      str
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

    try {
      const resp = await fetch(`${apiBaseUrl}/sessions/${encodeURIComponent(sessionId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform,
          candidate_name: candidateName.trim() || null,
          candidate_email: candidateEmail.trim() || null,
          interviewer_names: parseList(interviewerNames),
          expected_participants: parseList(expectedParticipants),
          llm_base_url: llmBaseUrl.trim() || null,
          llm_api_key: llmApiKey.trim() || null,
          llm_model: llmModel.trim() || null,
        }),
      });

      if (!resp.ok && resp.status !== 409) {
        const errJson = await resp.json().catch(() => ({ error: resp.statusText }));
        throw new Error(errJson.error || `Failed to start session (${resp.status})`);
      }

      setSuccessMsg(
        resp.status === 409
          ? `Connected to existing session "${sessionId}"`
          : `Started new live session "${sessionId}"`
      );
      onSessionChanged(sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="rounded-[28px] border border-stone-200 bg-white/90 p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-stone-500">
            Session Configuration & Available Data
          </h2>
          <p className="mt-1 text-xs text-stone-600">
            Enter external metadata (candidate name/email, schedule, interviewers) & LLM model configuration
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          className="rounded-full border border-stone-300 bg-stone-100 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-200 transition"
        >
          {isOpen ? "Hide Form" : "Configure / Start Session"}
        </button>
      </div>

      {isOpen && (
        <form onSubmit={handleStartSession} className="mt-4 grid gap-4 border-t border-stone-100 pt-4 text-sm">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-stone-600">Session ID</label>
              <input
                type="text"
                value={sessionId}
                onChange={(e) => setSessionId(e.target.value)}
                required
                className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-1.5 text-stone-800 focus:border-amber-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-stone-600">Platform</label>
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value as "meet" | "zoom")}
                className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-1.5 text-stone-800 focus:border-amber-500 focus:outline-none"
              >
                <option value="meet">Google Meet</option>
                <option value="zoom">Zoom</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-stone-600">Candidate Name (Metadata)</label>
              <input
                type="text"
                value={candidateName}
                onChange={(e) => setCandidateName(e.target.value)}
                placeholder="e.g. Rahul Sharma"
                className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-1.5 text-stone-800 focus:border-amber-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-stone-600">Candidate Email</label>
              <input
                type="email"
                value={candidateEmail}
                onChange={(e) => setCandidateEmail(e.target.value)}
                placeholder="e.g. rahul@example.com"
                className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-1.5 text-stone-800 focus:border-amber-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-stone-600">
                Interviewer Names (comma-separated)
              </label>
              <input
                type="text"
                value={interviewerNames}
                onChange={(e) => setInterviewerNames(e.target.value)}
                placeholder="e.g. Ashwini Kumar, Priya Patel"
                className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-1.5 text-stone-800 focus:border-amber-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-stone-600">
                Expected Participants (Calendar Invite)
              </label>
              <input
                type="text"
                value={expectedParticipants}
                onChange={(e) => setExpectedParticipants(e.target.value)}
                placeholder="e.g. Rahul Sharma, Ashwini Kumar"
                className="mt-1 w-full rounded-xl border border-stone-300 px-3 py-1.5 text-stone-800 focus:border-amber-500 focus:outline-none"
              />
            </div>
          </div>

          {/* LLM Provider Configuration Section */}
          <div className="rounded-2xl border border-amber-200/60 bg-amber-50/50 p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-900">
                LLM Provider Configuration (Optional)
              </h3>
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                Real or Scripted Fallback
              </span>
            </div>
            <p className="mt-1 text-xs text-stone-600 leading-relaxed">
              Configure a custom endpoint (e.g., <code className="bg-white px-1 py-0.5 rounded">http://localhost:4001</code>) and API Key (<code className="bg-white px-1 py-0.5 rounded">sk-1234</code>). If left empty, the system automatically uses deterministic offline evaluation (<code className="bg-white px-1 py-0.5 rounded">ScriptedLLMProvider</code>).
            </p>

            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label className="block text-[11px] font-medium text-stone-600">LLM Base URL</label>
                <input
                  type="text"
                  value={llmBaseUrl}
                  onChange={(e) => setLlmBaseUrl(e.target.value)}
                  placeholder="http://localhost:4001"
                  className="mt-1 w-full rounded-xl border border-stone-300 bg-white px-3 py-1.5 text-xs text-stone-800 focus:border-amber-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-stone-600">LLM API Key</label>
                <input
                  type="password"
                  value={llmApiKey}
                  onChange={(e) => setLlmApiKey(e.target.value)}
                  placeholder="sk-1234"
                  className="mt-1 w-full rounded-xl border border-stone-300 bg-white px-3 py-1.5 text-xs text-stone-800 focus:border-amber-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-[11px] font-medium text-stone-600">LLM Model Name</label>
                <input
                  type="text"
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  placeholder="gpt-4o-mini"
                  className="mt-1 w-full rounded-xl border border-stone-300 bg-white px-3 py-1.5 text-xs text-stone-800 focus:border-amber-500 focus:outline-none"
                />
              </div>
            </div>
          </div>

          {error && <div className="rounded-xl bg-red-50 p-3 text-xs text-red-700">{error}</div>}
          {successMsg && (
            <div className="rounded-xl bg-emerald-50 p-3 text-xs text-emerald-700">{successMsg}</div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="submit"
              disabled={loading}
              className="rounded-xl bg-amber-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-amber-700 disabled:opacity-50 transition"
            >
              {loading ? "Starting Session..." : "Prime & Start Session"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
};
