// content-script.js -- isolated-world script injected into meet.google.com.
// Two jobs: (1) observe the participant-tile DOM to emit control events
// (join/leave/rename/webcam/screen-share), (2) relay inject.js's
// (MAIN-world) captured audio chunks up to background.js.
//
// IMPORTANT: the CSS selectors below are a best-effort guess at Meet's tile
// structure (data-participant-id-style attributes and aria-labels are what
// Meet has used historically), NOT verified against a live call in this
// session -- there is no way to do that without actually opening
// meet.google.com with a real account. Re-check these against the current
// live DOM before relying on this in a real demo.

const TILE_SELECTOR = "[data-participant-id]";
const SPEAKING_CLASS_HINT = "speaking"; // best-effort; Meet's actual class name is unverified

const knownParticipants = new Map(); // participant_id -> { displayName, joinOrder }
let joinOrderCounter = 0;
let activeConnectionId = null; // best-effort correlation target for inject.js audio chunks

function nowSec() {
  return performance.now() / 1000;
}

function sendControlEvent(type, payload) {
  chrome.runtime.sendMessage({
    target: "background",
    kind: "control",
    type,
    ts: nowSec(),
    payload,
  });
}

function participantIdFromTile(tile) {
  return tile.getAttribute("data-participant-id") || tile.id || null;
}

function displayNameFromTile(tile) {
  const label = tile.getAttribute("aria-label") || tile.querySelector("[data-self-name]")?.textContent;
  return (label || "Unknown").trim();
}

function handleTileAdded(tile) {
  const participantId = participantIdFromTile(tile);
  if (!participantId || knownParticipants.has(participantId)) return;
  const displayName = displayNameFromTile(tile);
  joinOrderCounter += 1;
  knownParticipants.set(participantId, { displayName, joinOrder: joinOrderCounter });
  sendControlEvent("PARTICIPANT_JOINED", {
    participant_id: participantId,
    display_name: displayName,
    email: null,
    device_name: null,
    join_order: joinOrderCounter,
  });
}

function handleTileRemoved(tile) {
  const participantId = participantIdFromTile(tile);
  if (!participantId || !knownParticipants.has(participantId)) return;
  knownParticipants.delete(participantId);
  sendControlEvent("PARTICIPANT_LEFT", { participant_id: participantId, leave_ts: nowSec() });
}

function observeTiles() {
  document.querySelectorAll(TILE_SELECTOR).forEach(handleTileAdded);

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.matches?.(TILE_SELECTOR)) handleTileAdded(node);
        node.querySelectorAll?.(TILE_SELECTOR).forEach(handleTileAdded);
      }
      for (const node of mutation.removedNodes) {
        if (!(node instanceof HTMLElement)) continue;
        if (node.matches?.(TILE_SELECTOR)) handleTileRemoved(node);
        node.querySelectorAll?.(TILE_SELECTOR).forEach(handleTileRemoved);
      }
      // Best-effort active-speaker tracking, for correlating inject.js's
      // per-connection audio chunks to a participant_id.
      if (mutation.type === "attributes" && mutation.target instanceof HTMLElement) {
        const tile = mutation.target.closest(TILE_SELECTOR);
        if (tile && tile.classList.contains(SPEAKING_CLASS_HINT)) {
          activeConnectionId = participantIdFromTile(tile);
        }
      }
    }
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
  });
}

// Relay inject.js's (MAIN-world) postMessage events up to background.js.
window.addEventListener("message", (event) => {
  if (event.source !== window || event.data?.source !== "cis-inject") return;
  const msg = event.data;

  if (msg.kind === "audio-chunk") {
    chrome.runtime.sendMessage({
      target: "background",
      kind: "audio-chunk",
      // Best-effort: attribute this connection's audio to whichever tile is
      // currently marked as speaking; falls back to the raw connection id
      // if no active speaker has been observed yet.
      participant_id: activeConnectionId || msg.connectionId,
      start_sec: msg.startSec,
      end_sec: msg.endSec,
      buffer: Array.from(new Uint8Array(msg.buffer)), // structured-clone-safe for runtime.sendMessage
    });
  }
});

observeTiles();
