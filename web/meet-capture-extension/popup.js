const sessionInput = document.getElementById("session-id");
const serverBaseUrlInput = document.getElementById("server-base-url");
const statusEl = document.getElementById("status");

chrome.storage.local.get(["sessionId", "serverBaseUrl"], ({ sessionId, serverBaseUrl }) => {
  if (sessionId) sessionInput.value = sessionId;
  serverBaseUrlInput.value = serverBaseUrl || "http://localhost:8000";
});

document.getElementById("start").addEventListener("click", async () => {
  const sessionId = sessionInput.value.trim();
  const serverBaseUrl = serverBaseUrlInput.value.trim() || "http://localhost:8000";
  if (!sessionId) {
    statusEl.textContent = "Enter a session ID first.";
    return;
  }
  await chrome.storage.local.set({ sessionId, serverBaseUrl });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.runtime.sendMessage({
    kind: "start-capture",
    sessionId,
    serverBaseUrl,
    tabId: tab?.id,
  });
  statusEl.textContent = `Capturing ${sessionId} to ${serverBaseUrl}`;
});

document.getElementById("stop").addEventListener("click", () => {
  chrome.runtime.sendMessage({ kind: "stop-capture" });
  statusEl.textContent = "Stopped.";
});

// Randomize Meet Participants features
const shuffle = document.getElementById('shuffle');
const list = document.getElementById('list');
const inputList = document.getElementById('custom-list-area');
const inputListBt = document.getElementById('custom-list-bt');

const printParticipantsList = (participants) => {
  if (!participants || participants.length === 0) {
    list.innerHTML = "<li>No participants found</li>";
    return;
  }
  list.innerHTML = participants
    .map((participant, index) => `<li>${index + 1} - ${participant}</li>`)
    .join('');
};

if (shuffle) {
  shuffle.onclick = () => {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      if (!tabs || !tabs[0]) return;
      let participants = null;
      if (inputList && inputList.value !== '') {
        const regex = /,|\n/gm;
        participants = inputList.value.split(regex).map(s => s.trim()).filter(Boolean);
      }
      chrome.tabs.sendMessage(
        tabs[0].id,
        { action: 'randomize', participants },
        function (response) {
          if (chrome.runtime.lastError) {
            // Extension might not be injected in current tab or tab is not Google Meet
            list.innerHTML = "<li>Open a Google Meet call to shuffle participants</li>";
            return;
          }
          if (response && response.data) {
            printParticipantsList(response.data);
          }
        }
      );
    });
  };

  shuffle.click();
}

if (inputListBt) {
  inputListBt.onclick = () => {
    if (inputList.parentNode.classList.contains('hidden')) {
      inputList.value = '';
      inputList.parentNode.classList.remove('hidden');
      inputListBt.setAttribute('src', 'images/hide.png');
      inputListBt.setAttribute('title', 'Hide custom list');
    } else {
      inputList.parentNode.classList.add('hidden');
      inputListBt.setAttribute('src', 'images/list.png');
      inputListBt.setAttribute('title', 'Add custom list');
    }
  };
}

const extractNamesBt = document.getElementById('extract-names');
if (extractNamesBt) {
  extractNamesBt.onclick = () => {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      if (!tabs || !tabs[0]) return;
      chrome.tabs.sendMessage(
        tabs[0].id,
        { action: 'extract_names' },
        function (response) {
          if (chrome.runtime.lastError) {
            list.innerHTML = "<li>Open a Google Meet call to extract participants</li>";
            return;
          }
          if (response && response.data) {
            printParticipantsList(response.data);
          }
        }
      );
    });
  };
}

