const btn = document.getElementById("btn");
const statusEl = document.getElementById("status");
const connEl = document.getElementById("conn");
const urlInput = document.getElementById("url");
const toggle = document.getElementById("toggle");
const config = document.getElementById("config");
const save = document.getElementById("save");
const micBtn = document.getElementById("mic");

const DEFAULT_WEB = "http://127.0.0.1:8751";

toggle.addEventListener("click", () => {
  config.classList.toggle("show");
  toggle.textContent = config.classList.contains("show")
    ? "Hide settings"
    : "Settings";
});

save.addEventListener("click", () => {
  chrome.storage.local.set(
    { webUrl: urlInput.value.replace(/\/+$/, "") },
    () => {
      save.textContent = "Saved";
      setTimeout(() => {
        save.textContent = "Save";
      }, 1200);
      connectToShelby();
    },
  );
});

// Try a single URL: fetch the page, look for the token meta tag.
// Returns { token, backendUrl } on success, null on failure.
async function tryUrl(url) {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    const resp = await fetch(url, {
      credentials: "omit",
      signal: ctrl.signal,
    });
    clearTimeout(timer);

    const html = await resp.text();
    const m = html.match(
      /<meta\s+name="assistant-token"\s+content="([^"]+)"/,
    );
    if (!m) return null;

    // Mirror the web app's own logic for finding the backend (web/src/api.ts):
    // - assistant-api-url meta tag wins (full URL, for ngrok etc.)
    // - on localhost, always port 8750
    // - on any other host, read assistant-api-port (for Tailscale etc.)
    const u = new URL(url);
    const fullUrlMatch = html.match(
      /<meta\s+name="assistant-api-url"\s+content="([^"]+)"/,
    );
    let backendUrl;
    if (fullUrlMatch) {
      backendUrl = fullUrlMatch[1];
    } else if (
      u.hostname === "127.0.0.1" ||
      u.hostname === "localhost"
    ) {
      backendUrl = `http://${u.hostname}:8750`;
    } else {
      const portMatch = html.match(
        /<meta\s+name="assistant-api-port"\s+content="(\d+)"/,
      );
      u.port = portMatch ? portMatch[1] : "8750";
      backendUrl = u.origin;
    }

    return { webUrl: url, token: m[1], backendUrl };
  } catch {
    return null;
  }
}

// Scan open tabs for one that looks like Shelby (has the token meta tag).
// Returns a list of candidate URLs to try.
async function findShelbyTabs() {
  const tabs = await chrome.tabs.query({});
  const seen = new Set();
  const candidates = [];
  for (const tab of tabs) {
    if (!tab.url) continue;
    try {
      const origin = new URL(tab.url).origin;
      if (seen.has(origin)) continue;
      seen.add(origin);
      // Only check HTTP(S) tabs with a port (Shelby always runs on an explicit port)
      if (/^https?:/.test(origin) && /:\d+$/.test(origin)) {
        candidates.push(origin);
      }
    } catch {
      // invalid URL, skip
    }
  }
  return candidates;
}

async function connectToShelby() {
  connEl.textContent = "Looking for Shelby...";
  connEl.className = "conn";

  const { webUrl: stored } = await chrome.storage.local.get("webUrl");

  // 1. Try the stored URL
  if (stored) {
    const r = await tryUrl(stored);
    if (r) return connected(r);
  }

  // 2. Try localhost default
  if (stored !== DEFAULT_WEB) {
    const r = await tryUrl(DEFAULT_WEB);
    if (r) return connected(r);
  }

  // 3. Scan open tabs for anything serving Shelby's token
  const candidates = await findShelbyTabs();
  for (const url of candidates) {
    const r = await tryUrl(url);
    if (r) return connected(r);
  }

  connEl.textContent = "Can't find Shelby — is it running?";
  connEl.className = "conn fail";
  urlInput.value = stored || DEFAULT_WEB;
  return false;
}

function connected(result) {
  chrome.storage.local.set(result);
  connEl.textContent = `Connected — ${result.webUrl}`;
  connEl.className = "conn ok";
  urlInput.value = result.webUrl;
  return true;
}

async function init() {
  const state = await msg({ action: "get-status" });
  const ok = await connectToShelby();

  if (state && state.recording) {
    btn.textContent = "Stop Recording";
    btn.className = "stop";
    btn.disabled = state.stopping;
    statusEl.textContent = state.stopping
      ? "Stopping and uploading..."
      : "Recording in progress...";
    statusEl.className = state.stopping
      ? "status uploading"
      : "status recording";
  } else {
    btn.disabled = !ok;
  }
}

// The upload finishes after Stop is pressed; say how it went and let a new recording start.
chrome.runtime.onMessage.addListener((message) => {
  if (message.action !== "upload-complete" && message.action !== "upload-error") {
    return;
  }
  btn.textContent = "Start Recording";
  btn.className = "start";
  btn.disabled = false;
  if (message.action === "upload-complete") {
    statusEl.textContent = `Uploaded ${message.result.name}`;
    statusEl.className = "status";
  } else {
    statusEl.textContent = message.error;
    statusEl.className = "status error";
  }
});

btn.addEventListener("click", async () => {
  const state = await msg({ action: "get-status" });

  if (state && state.recording) {
    btn.disabled = true;
    statusEl.textContent = "Stopping and uploading...";
    statusEl.className = "status uploading";
    await connectToShelby();

    const r = await msg({ action: "stop-capture" });
    if (r && r.error) {
      statusEl.textContent = r.error;
      statusEl.className = "status error";
      btn.disabled = false;
    }
    return;
  }

  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (!tab) {
    statusEl.textContent = "No active tab";
    statusEl.className = "status error";
    return;
  }

  btn.disabled = true;
  statusEl.textContent = "Starting capture...";

  try {
    const streamId = await chrome.tabCapture.getMediaStreamId({
      targetTabId: tab.id,
    });

    const r = await msg({
      action: "start-capture",
      streamId,
      tabId: tab.id,
    });

    if (r && r.error) {
      statusEl.textContent = r.error;
      statusEl.className = "status error";
      btn.disabled = false;
      if (r.needsMic) micBtn.classList.add("show");
    } else {
      window.close();
    }
  } catch (err) {
    statusEl.textContent = err.message;
    statusEl.className = "status error";
    btn.disabled = false;
  }
});

// Chrome shows its microphone prompt on a normal page, not in the popup or the hidden recorder.
micBtn.addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("mic.html") });
});

function msg(payload) {
  return new Promise((resolve) =>
    chrome.runtime.sendMessage(payload, resolve),
  );
}

init();
