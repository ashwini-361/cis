const TILE_SELECTORS = [
  "[data-participant-id]",
  "[data-requested-participant-id]",
  "[data-self-name]",
];
const TRANSCRIPT_CONTAINER_SELECTORS = [
  '.a4cQT',
  '[aria-label*="Transcript"]',
  '[aria-label*="Captions"]',
  '[aria-label*="captions"]',
  '[aria-label*="transcript"]',
  '[role="log"][aria-live]',
];
const NAME_SELECTORS = [
  ".KcIKyf",
  ".jxFHg",
  "[data-self-name]",
  "[data-participant-name]",
  "[data-requested-participant-id] [dir=auto]",
];
const DOM_POLL_MS = 2000;
const PARTICIPANT_PANEL_BUTTON_SELECTORS = [
  'button[data-panel-id~="1"]',
  '*[data-tab-id~="1"]',
];
const REJECTED_NAME_TOKENS = [
  "frame_person",
  "keep_outline",
  "video_frame",
  "tile_wrapper",
  "placeholder",
  "layout",
  "unknown",
  "devices",
  "device",
  "microphone",
  "camera",
  "settings",
  "more options",
  "pin",
  "unpin",
  "presentation",
  "presenting",
  "turn off",
  "turn on",
  "mute",
  "unmute",
];
const TRANSCRIPT_TEXT_SELECTORS = ".bh44bd, .VbkSUe, [jsname='tgaKEf'], [class*='bh44bd']";
const TRANSCRIPT_SPEAKER_SELECTORS = ".KcIKyf, .jxFHg, [class*='KcIKyf']";
const REJECTED_TRANSCRIPT_PHRASES = [
  "your meeting s ready",
  "your meeting is ready",
  "add others",
  "copy link",
  "joined as",
  "meet google com",
  "must get your permission before they can join",
  "people who use this meeting link",
  "content copy",
  "close close",
  "or share this meeting link",
];

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

function normalizeTranscriptText(value) {
  return (value || "")
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isRejectedTranscriptText(value) {
  const normalized = normalizeTranscriptText(value);
  if (!normalized || normalized.length < 2) return true;
  if (normalized.includes("meet google com")) return true;
  return REJECTED_TRANSCRIPT_PHRASES.some(
    (phrase) => normalized === phrase || normalized.includes(phrase)
  );
}

function isLikelyTranscriptContainer(node) {
  if (!(node instanceof HTMLElement)) return false;
  const label = `${node.getAttribute("aria-label") || ""} ${node.id || ""}`;
  if (isRejectedTranscriptText(label)) return false;
  if (node.querySelector(TRANSCRIPT_TEXT_SELECTORS) && node.querySelector(TRANSCRIPT_SPEAKER_SELECTORS)) {
    return true;
  }
  const liveLabel = (node.getAttribute("aria-live") || "").toLowerCase();
  return liveLabel.length > 0 && !isRejectedTranscriptText(node.innerText || "");
}

function participantIdFromTile(tile) {
  return (
    tile.getAttribute("data-participant-id") ||
    tile.getAttribute("data-requested-participant-id") ||
    null
  );
}

function isValidParticipantId(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function isSuspiciousParticipantName(name) {
  const normalized = normalizeName(name);
  if (!normalized || normalized.length < 2) return true;
  return REJECTED_NAME_TOKENS.some((token) => normalized === token || normalized.includes(token));
}

function displayNameFromTile(tile) {
  for (const selector of NAME_SELECTORS) {
    const text = tile.querySelector(selector)?.textContent?.trim();
    if (text && !isSuspiciousParticipantName(text)) return text;
  }
  const selfName = tile.getAttribute("data-self-name") || "";
  if (selfName.trim() && !isSuspiciousParticipantName(selfName)) return selfName.trim();
  return "Unknown";
}

function openParticipantsPanelButton() {
  for (const selector of PARTICIPANT_PANEL_BUTTON_SELECTORS) {
    const button = document.querySelector(selector);
    if (button instanceof HTMLElement) return button;
  }
  return null;
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

function canonicalSidebarEntries() {
  const listItems = Array.from(document.querySelectorAll('*[role="listitem"]'));
  return listItems
    .map((node, index) => {
      const details = extractParticipantDetailsFromNode(node);
      if (!details || !details.displayName) return null;
      if (isSuspiciousParticipantName(details.displayName)) return null;
      return {
        ...details,
        syntheticId: `sidebar-${normalizeName(details.displayName)}-${index}`,
      };
    })
    .filter(Boolean);
}

function getParticipantTiles() {
  const tiles = new Map();
  for (const selector of TILE_SELECTORS) {
    document.querySelectorAll(selector).forEach((node) => {
      const tile = node instanceof HTMLElement ? node.closest(selector) || node : null;
      if (!(tile instanceof HTMLElement)) return;
      const participantId = participantIdFromTile(tile);
      if (!isValidParticipantId(participantId)) return;
      tiles.set(participantId, tile);
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
  const sidebarEntries = canonicalSidebarEntries();
  const sidebarNames = new Set(sidebarEntries.map((entry) => normalizeName(entry.displayName)));
  const tiles = getParticipantTiles();
  const seenParticipantIds = new Set();
  const tileNameCounts = new Map();

  for (const [participantId, tile] of tiles.entries()) {
    const displayName = displayNameFromTile(tile);
    if (isSuspiciousParticipantName(displayName)) {
      sendDiagnostic(
        "content.participant_tile_rejected",
        "Rejected suspicious participant tile",
        { participantId, displayName, reason }
      );
      continue;
    }
    const normalizedName = normalizeName(displayName);
    if (sidebarNames.size > 0 && !sidebarNames.has(normalizedName)) {
      sendDiagnostic(
        "content.participant_tile_unmatched",
        "Ignored tile not present in contributors panel",
        { participantId, displayName, reason }
      );
      continue;
    }
    seenParticipantIds.add(participantId);
    tileNameCounts.set(normalizedName, (tileNameCounts.get(normalizedName) || 0) + 1);
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

  syncSidebarParticipants(sidebarEntries, seenParticipantIds, tileNameCounts);

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
  if (node.closest("button, dialog, [role='dialog']")) return null;
  const nameEl = node.querySelector(TRANSCRIPT_SPEAKER_SELECTORS);
  const textEl = node.querySelector(TRANSCRIPT_TEXT_SELECTORS);
  if (nameEl && textEl) {
    const speakerName = nameEl.innerText?.trim();
    const content = textEl.innerText?.trim();
    if (
      speakerName &&
      content &&
      content.length >= 2 &&
      !isSuspiciousParticipantName(speakerName) &&
      !isRejectedTranscriptText(speakerName) &&
      !isRejectedTranscriptText(content)
    ) {
      return { speakerName, text: content };
    }
  }

  const text = node.innerText?.trim();
  if (!text || text.length < 3 || isRejectedTranscriptText(text)) return null;
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) {
    const colonIndex = text.indexOf(":");
    if (colonIndex <= 0) return null;
    const speakerName = text.slice(0, colonIndex).trim();
    const content = text.slice(colonIndex + 1).trim();
    if (
      !speakerName ||
      !content ||
      isSuspiciousParticipantName(speakerName) ||
      isRejectedTranscriptText(speakerName) ||
      isRejectedTranscriptText(content)
    ) return null;
    return { speakerName, text: content };
  }
  const speakerName = lines[0];
  const content = lines.slice(1).join(" ").trim();
  if (
    !speakerName ||
    !content ||
    isSuspiciousParticipantName(speakerName) ||
    isRejectedTranscriptText(speakerName) ||
    isRejectedTranscriptText(content)
  ) return null;
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
      if (
        node instanceof HTMLElement &&
        isLikelyTranscriptContainer(node) &&
        !containers.includes(node)
      ) {
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

let autoCaptionsClicked = false;

function ensureCaptionsEnabled() {
  if (autoCaptionsClicked) return;
  const containers = currentTranscriptContainers();
  if (containers.length > 0) return;
  document.querySelectorAll("button").forEach((btn) => {
    const label = (btn.getAttribute("aria-label") || btn.innerText || "").toLowerCase();
    if (!autoCaptionsClicked && (label.includes("caption") || label.includes("subtitle") || label.includes("closed_caption"))) {
      autoCaptionsClicked = true;
      btn.click();
    }
  });
}

function bindTranscriptObserver() {
  ensureCaptionsEnabled();
  const containers = currentTranscriptContainers();

  if (containers.length === 0) {
    if (!transcriptSelectorReported) {
      transcriptSelectorReported = true;
      sendDiagnostic("content.transcript_selector_missing", "No transcript container found yet");
      sendDiagnostic("content.transcript_source_inactive", "Transcript source inactive");
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
  sendDiagnostic("content.transcript_source_active", "Transcript source active");

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

const shuffleArray = (array) => {
  let index = array.length - 1,
    randomIndex,
    tempValue;

  for (index; index > 0; index--) {
    randomIndex = Math.floor(Math.random() * index);
    tempValue = array[index];
    array[index] = array[randomIndex];
    array[randomIndex] = tempValue;
  }

  return array;
};

const getParticipantsContainer = () => {
  let participantsContainer;
  let firstKey = document.querySelector('*[data-sort-key]');

  while (firstKey && !participantsContainer) {
    if (firstKey.hasAttribute('data-is-persistent')) {
      participantsContainer = firstKey;
    }
    firstKey = firstKey.parentElement;
  }

  return participantsContainer;
};

const resetparticipantsContainerHeight = () => {
  const participantsContainer = getParticipantsContainer();

  if (participantsContainer && participantsContainer.style.height) {
    participantsContainer.style.height = '';
  }
};

const loadAllParticipants = async () => {
  return new Promise((resolve) => {
    setTimeout(() => {
      const participantsContainer = getParticipantsContainer();
      if (participantsContainer) {
        participantsContainer.style.height = '100000px';
        window.dispatchEvent(new CustomEvent('resize'));
        setTimeout(() => {
          resolve(participantsContainer);
        }, 300);
      } else {
        resolve(false);
      }
    }, 300);
  });
};

const extractAllParticipantNames = () => {
  const sidebarNames = canonicalSidebarEntries().map((entry) => entry.displayName);
  resetparticipantsContainerHeight();

  if (sidebarNames.length > 0) {
    return [...new Set(sidebarNames)];
  }

  const tileNames = Array.from(knownParticipants.values())
    .map((p) => p.displayName)
    .filter((n) => n && n !== "Unknown" && !isSuspiciousParticipantName(n));

  return [...new Set(tileNames)];
};

function extractParticipantDetailsFromNode(node) {
  if (!(node instanceof HTMLElement)) return null;
  const rawText = node.innerText || "";
  const lines = rawText.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0) return null;

  const displayName = lines[0].replace(/\(You\)/i, "").trim();
  if (!displayName || isSuspiciousParticipantName(displayName)) return null;

  const emailRegex = /([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/;
  let email = null;
  let roleLabel = null;

  for (const line of lines) {
    const match = emailRegex.exec(line);
    if (match) {
      email = match[1];
    } else if (
      line.toLowerCase().includes("host") ||
      line.toLowerCase().includes("external") ||
      line.toLowerCase().includes("guest")
    ) {
      roleLabel = line;
    }
  }

  if (!email) {
    const ariaLabel = node.getAttribute("aria-label") || "";
    const match = emailRegex.exec(ariaLabel);
    if (match) email = match[1];
  }

  return {
    displayName,
    email,
    roleLabel,
    isSelf: /\(you\)/i.test(lines[0]),
  };
}

function syncSidebarParticipants(sidebarEntries, seenParticipantIds, tileNameCounts) {
  const sidebarNameCounts = new Map();

  for (const entry of sidebarEntries) {
    const normalizedName = normalizeName(entry.displayName);
    sidebarNameCounts.set(normalizedName, (sidebarNameCounts.get(normalizedName) || 0) + 1);

    let matchedId = null;
    for (const [id, existing] of knownParticipants.entries()) {
      if (normalizeName(existing.displayName) !== normalizedName) continue;
      if (id.startsWith("sidebar-")) continue;
      matchedId = id;
      break;
    }

    if (matchedId) {
      seenParticipantIds.add(matchedId);
      const existing = knownParticipants.get(matchedId);
      if (existing && entry.email && !existing.email) {
        existing.email = entry.email;
      }
      continue;
    }

    const tileCount = tileNameCounts.get(normalizedName) || 0;
    const sidebarCount = sidebarNameCounts.get(normalizedName) || 0;
    if (tileCount >= sidebarCount) {
      continue;
    }

    const syntheticId = entry.syntheticId;
    const existingSynthetic = knownParticipants.get(syntheticId);
    if (existingSynthetic) {
      seenParticipantIds.add(syntheticId);
      if (entry.email && !existingSynthetic.email) {
        existingSynthetic.email = entry.email;
      }
      continue;
    }

    joinOrderCounter += 1;
    knownParticipants.set(syntheticId, {
      displayName: entry.displayName,
      email: entry.email || null,
      joinOrder: joinOrderCounter,
      webcamOn: null,
      screenShare: false,
    });
    seenParticipantIds.add(syntheticId);
    sendControlEvent("PARTICIPANT_JOINED", {
      participant_id: syntheticId,
      display_name: entry.displayName,
      email: entry.email || null,
      device_name: null,
      join_order: joinOrderCounter,
    });
    sendDiagnostic(
      "content.sidebar_participant_discovered",
      `Extracted participant from Meet sidebar: ${entry.displayName}`,
      {
        participant_id: syntheticId,
        display_name: entry.displayName,
        email: entry.email || null,
        is_self: entry.isSelf,
      }
    );
  }
}

const randomizeParticipants = () => {
  return shuffleArray(extractAllParticipantNames());
};

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "extract_names") {
    (async () => {
      const showParticipantsButton =
        openParticipantsPanelButton();

      if (showParticipantsButton) {
        if (showParticipantsButton.getAttribute("aria-pressed") !== "true") {
          showParticipantsButton.click();
        }
        await loadAllParticipants();
      }
      sendResponse({ data: extractAllParticipantNames() });
    })();
    return true;
  }

  if (request.action === "randomize") {
    if (request.participants !== null && Array.isArray(request.participants) && request.participants.length > 0) {
      setTimeout(() => sendResponse({ data: shuffleArray(request.participants) }));
    } else {
      (async () => {
        const showParticipantsButton =
          openParticipantsPanelButton();

        if (showParticipantsButton) {
          if (showParticipantsButton.getAttribute("aria-pressed") !== "true") {
            showParticipantsButton.click();
          }
          await loadAllParticipants();
          sendResponse({ data: randomizeParticipants() });
        } else {
          sendResponse({ data: extractAllParticipantNames() });
        }
      })();
    }
    return true;
  }
});

observeMeetDom();
