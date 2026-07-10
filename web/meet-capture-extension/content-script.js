const TILE_SELECTORS = [
  "[data-participant-id]",
  "[data-requested-participant-id]",
  "[data-self-name]",
];
const TRANSCRIPT_CONTAINER_SELECTORS = [
  '[aria-label*="Transcript"]',
  '[aria-label*="Captions"]',
  '[role="log"][aria-live]',
  '[aria-live="polite"]',
  '[aria-live="assertive"]',
];
const NAME_SELECTORS = [
  "[data-self-name]",
  "[data-participant-name]",
  "[data-requested-participant-id] [dir=auto]",
  "[aria-label]",
];
const DOM_POLL_MS = 2000;

const knownParticipants = new Map();
const emittedTranscriptKeys = new Set();
const connectionParticipantMap = new Map();
const knownConnectionIds = new Set();
const reportedUnmappedConnectionIds = new Set();
let joinOrderCounter = 0;
let participantSelectorReported = false;
let transcriptSelectorReported = false;
let transcriptObserver = null;
let transcriptObserverSignature = "";
let domPollStarted = false;

function nowSec() {
  return performance.now() / 1000;
}

function sendToBackground(message) {
  chrome.runtime.sendMessage({ target: "background", ...message });
}

function sendControlEvent(type, payload) {
  sendToBackground({ kind: "control", type, ts: nowSec(), payload });
}

function sendDiagnostic(event, message, payload = {}) {
  sendToBackground({ kind: "diagnostic", event, message, payload, ts: nowSec() });
}

function normalizeName(value) {
  return (value || "")
    .toLowerCase()
    .replace(/\(you\)/g, "")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function participantIdFromTile(tile) {
  return (
    tile.getAttribute("data-participant-id") ||
    tile.getAttribute("data-requested-participant-id") ||
    tile.id ||
    null
  );
}

function displayNameFromTile(tile) {
  for (const selector of NAME_SELECTORS) {
    const text = tile.querySelector(selector)?.textContent?.trim();
    if (text) return text;
  }
  const aria = tile.getAttribute("aria-label") || "";
  if (aria.trim()) return aria.trim();
  return "Unknown";
}

function detectWebcamOn(tile) {
  const label = `${tile.getAttribute("aria-label") || ""} ${tile.textContent || ""}`.toLowerCase();
  if (label.includes("camera off") || label.includes("video off")) return false;
  if (tile.querySelector("video")) return true;
  return null;
}

function detectScreenShare(tile) {
  const label = `${tile.getAttribute("aria-label") || ""} ${tile.textContent || ""}`.toLowerCase();
  if (label.includes("presenting") || label.includes("screen share") || label.includes("sharing")) {
    return true;
  }
  return false;
}

function mappedParticipantIds() {
  return new Set(connectionParticipantMap.values());
}

function assignConnectionParticipant(connectionId, participantId, reason) {
  if (!connectionId || !participantId || !knownParticipants.has(participantId)) return false;

  const existingParticipantId = connectionParticipantMap.get(connectionId);
  if (existingParticipantId === participantId) return true;

  for (const [mappedConnectionId, mappedParticipantId] of connectionParticipantMap.entries()) {
    if (mappedConnectionId !== connectionId && mappedParticipantId === participantId) {
      return false;
    }
  }

  connectionParticipantMap.set(connectionId, participantId);
  sendDiagnostic("content.connection_mapped", "Mapped WebRTC connection to participant", {
    connectionId,
    participantId,
    reason,
  });
  return true;
}

function maybeAutoMapConnections(reason) {
  const mappedIds = mappedParticipantIds();
  const unmappedConnectionIds = [...knownConnectionIds].filter(
    (connectionId) => !connectionParticipantMap.has(connectionId)
  );
  const unmappedParticipantIds = [...knownParticipants.keys()].filter(
    (participantId) => !mappedIds.has(participantId)
  );

  if (unmappedConnectionIds.length === 1 && unmappedParticipantIds.length === 1) {
    assignConnectionParticipant(unmappedConnectionIds[0], unmappedParticipantIds[0], reason);
  }
}

function participantIdForSpeakerName(name) {
  const normalized = normalizeName(name);
  if (!normalized) return null;
  for (const [participantId, participant] of knownParticipants.entries()) {
    const participantName = normalizeName(participant.displayName);
    if (!participantName) continue;
    if (participantName === normalized) return participantId;
    if (participantName.includes(normalized) || normalized.includes(participantName)) {
      return participantId;
    }
  }
  return null;
}

function getParticipantTiles() {
  const tiles = new Map();
  for (const selector of TILE_SELECTORS) {
    document.querySelectorAll(selector).forEach((node) => {
      const tile = node instanceof HTMLElement ? node.closest(selector) || node : null;
      if (!(tile instanceof HTMLElement)) return;
      const participantId = participantIdFromTile(tile);
      if (participantId) tiles.set(participantId, tile);
    });
  }
  if (tiles.size > 0 && !participantSelectorReported) {
    participantSelectorReported = true;
    sendDiagnostic("content.participant_selector_found", "Participant tile selector matched", {
      count: tiles.size,
    });
  }
  if (tiles.size === 0 && !participantSelectorReported) {
    sendDiagnostic("content.participant_selector_missing", "No participant tiles found yet");
  }
  return tiles;
}

function syncParticipantTiles(reason) {
  const tiles = getParticipantTiles();
  const seenParticipantIds = new Set();

  for (const [participantId, tile] of tiles.entries()) {
    seenParticipantIds.add(participantId);
    const displayName = displayNameFromTile(tile);
    const webcamOn = detectWebcamOn(tile);
    const screenShare = detectScreenShare(tile);
    const existing = knownParticipants.get(participantId);

    if (!existing) {
      joinOrderCounter += 1;
      knownParticipants.set(participantId, {
        displayName,
        joinOrder: joinOrderCounter,
        webcamOn,
        screenShare,
      });
      sendControlEvent("PARTICIPANT_JOINED", {
        participant_id: participantId,
        display_name: displayName,
        email: null,
        device_name: null,
        join_order: joinOrderCounter,
      });
      continue;
    }

    if (displayName && displayName !== existing.displayName) {
      sendControlEvent("PARTICIPANT_RENAMED", {
        participant_id: participantId,
        old_name: existing.displayName,
        new_name: displayName,
      });
      existing.displayName = displayName;
    }

    if (typeof webcamOn === "boolean" && webcamOn !== existing.webcamOn) {
      sendControlEvent(webcamOn ? "WEBCAM_ON" : "WEBCAM_OFF", {
        participant_id: participantId,
      });
      existing.webcamOn = webcamOn;
    }

    if (typeof screenShare === "boolean" && screenShare !== existing.screenShare) {
      sendControlEvent(screenShare ? "SCREEN_SHARE_START" : "SCREEN_SHARE_STOP", {
        participant_id: participantId,
      });
      existing.screenShare = screenShare;
    }
  }

  for (const [participantId] of knownParticipants.entries()) {
    if (seenParticipantIds.has(participantId)) continue;
    knownParticipants.delete(participantId);
    for (const [connectionId, mappedParticipantId] of connectionParticipantMap.entries()) {
      if (mappedParticipantId === participantId) {
        connectionParticipantMap.delete(connectionId);
      }
    }
    sendControlEvent("PARTICIPANT_LEFT", {
      participant_id: participantId,
      leave_ts: nowSec(),
    });
  }

  maybeAutoMapConnections(reason);
}

function parseTranscriptEntry(node) {
  if (!(node instanceof HTMLElement)) return null;
  const text = node.innerText?.trim();
  if (!text || text.length < 3) return null;
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) {
    const colonIndex = text.indexOf(":");
    if (colonIndex <= 0) return null;
    const speakerName = text.slice(0, colonIndex).trim();
    const content = text.slice(colonIndex + 1).trim();
    if (!speakerName || !content) return null;
    return { speakerName, text: content };
  }
  const speakerName = lines[0];
  const content = lines.slice(1).join(" ").trim();
  if (!speakerName || !content) return null;
  return { speakerName, text: content };
}

function emitTranscriptFromNode(node) {
  const parsed = parseTranscriptEntry(node);
  if (!parsed) return;
  const participantId = participantIdForSpeakerName(parsed.speakerName) || normalizeName(parsed.speakerName);
  if (!participantId) return;
  const key = `${participantId}|${parsed.text}`;
  if (emittedTranscriptKeys.has(key)) return;
  emittedTranscriptKeys.add(key);
  maybeAutoMapConnections("transcript");
  const ts = nowSec();
  sendToBackground({
    kind: "transcript",
    participant_id: participantId,
    speaker_name: parsed.speakerName,
    text: parsed.text,
    start_sec: ts,
    end_sec: ts,
  });
}

function currentTranscriptContainers() {
  const containers = [];
  for (const selector of TRANSCRIPT_CONTAINER_SELECTORS) {
    document.querySelectorAll(selector).forEach((node) => {
      if (node instanceof HTMLElement && !containers.includes(node)) {
        containers.push(node);
      }
    });
  }
  return containers;
}

function transcriptContainerSignature(containers) {
  return containers
    .map((node, index) => node.getAttribute("aria-label") || node.id || `${node.tagName}:${index}`)
    .join("|");
}

function bindTranscriptObserver() {
  const containers = currentTranscriptContainers();

  if (containers.length === 0) {
    if (!transcriptSelectorReported) {
      transcriptSelectorReported = true;
      sendDiagnostic("content.transcript_selector_missing", "No transcript container found yet");
    }
    return;
  }

  const signature = transcriptContainerSignature(containers);
  if (transcriptObserver && signature === transcriptObserverSignature) {
    return;
  }

  transcriptObserver?.disconnect();
  transcriptObserverSignature = signature;

  sendDiagnostic("content.transcript_selector_found", "Transcript container matched", {
    count: containers.length,
  });

  for (const container of containers) {
    container.querySelectorAll("div, li").forEach(emitTranscriptFromNode);
  }

  transcriptObserver = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        emitTranscriptFromNode(node);
        node.querySelectorAll?.("div, li").forEach(emitTranscriptFromNode);
      }
      if (mutation.type === "characterData" && mutation.target.parentElement) {
        emitTranscriptFromNode(mutation.target.parentElement);
      }
    }
  });

  for (const container of containers) {
    transcriptObserver.observe(container, { childList: true, subtree: true, characterData: true });
  }
}

function observeMeetDom() {
  syncParticipantTiles("initial");
  bindTranscriptObserver();
  sendDiagnostic("content.observer_started", "Meet DOM observers attached");

  const observer = new MutationObserver((mutations) => {
    let shouldSyncParticipants = false;
    let shouldRebindTranscript = false;

    for (const mutation of mutations) {
      if (mutation.type === "childList") {
        shouldSyncParticipants = true;
        shouldRebindTranscript = true;
      }
      if (mutation.type === "attributes" && mutation.target instanceof HTMLElement) {
        const tile = mutation.target.closest(TILE_SELECTORS.join(", "));
        if (tile) {
          shouldSyncParticipants = true;
        }
      }
    }

    if (shouldSyncParticipants) syncParticipantTiles("mutation");
    if (shouldRebindTranscript) bindTranscriptObserver();
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "aria-label"],
    characterData: false,
  });

  if (!domPollStarted) {
    domPollStarted = true;
    setInterval(() => {
      syncParticipantTiles("poll");
      bindTranscriptObserver();
    }, DOM_POLL_MS);
  }
}

window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.source !== "cis-inject") return;
  const msg = event.data;

  if (msg.kind === "connection-created" || msg.kind === "track-added") {
    knownConnectionIds.add(msg.connectionId);
    maybeAutoMapConnections(msg.kind);
    sendDiagnostic(`inject.${msg.kind}`, `Inject event: ${msg.kind}`, msg);
    return;
  }

  if (msg.kind === "audio-chunk") {
    maybeAutoMapConnections("audio_chunk");
    const participantId = connectionParticipantMap.get(msg.connectionId) || msg.connectionId;
    if (!connectionParticipantMap.has(msg.connectionId) && !reportedUnmappedConnectionIds.has(msg.connectionId)) {
      reportedUnmappedConnectionIds.add(msg.connectionId);
      sendDiagnostic("content.unmapped_connection", "Audio chunk arrived before a participant mapping was inferred", {
        connectionId: msg.connectionId,
      });
    }
    sendToBackground({
      kind: "audio-chunk",
      participant_id: participantId,
      start_sec: msg.startSec,
      end_sec: msg.endSec,
      buffer: Array.from(new Uint8Array(msg.buffer)),
    });
    return;
  }

  if (msg.kind === "track-error") {
    sendDiagnostic("inject.track-error", "Inject event: track-error", msg);
  }
});

observeMeetDom();
