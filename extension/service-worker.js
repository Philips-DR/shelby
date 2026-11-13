// Chrome stops this worker after about 30 seconds idle and wipes its variables, while the
// offscreen page goes on recording. So what it must remember lives in session storage.
const IDLE = { recording: false, recordingTabId: null, stopping: false };

const setState = (state) => chrome.storage.session.set({ state });

async function getState() {
  const { state } = await chrome.storage.session.get("state");
  if (!state || !state.recording) return IDLE;
  // The recording lives in the offscreen page. Without that page there is nothing recording.
  if (!(await hasOffscreen())) {
    await setState(IDLE);
    return IDLE;
  }
  return state;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "get-status") {
    getState().then(sendResponse);
    return true;
  }

  if (message.action === "start-capture") {
    handleStart(message.streamId, message.tabId).then(sendResponse);
    return true;
  }

  if (message.action === "stop-capture") {
    handleStop().then(sendResponse);
    return true;
  }

  if (message.action === "upload-complete") {
    setState(IDLE);
    chrome.action.setBadgeText({ text: "" });
    closeOffscreen();
  }

  if (message.action === "upload-error") {
    setState(IDLE);
    chrome.action.setBadgeText({ text: "ERR" });
    chrome.action.setBadgeBackgroundColor({ color: "#d32f2f" });
    setTimeout(() => {
      chrome.action.setBadgeText({ text: "" });
      closeOffscreen();
    }, 3000);
  }
});

async function handleStart(streamId, tabId) {
  if ((await getState()).recording) return { error: "Already recording" };

  try {
    await ensureOffscreen();

    // The recorder answers once the capture is really running, or with why it is not.
    const r = await chrome.runtime.sendMessage({
      action: "offscreen-start",
      streamId,
    });
    if (!r || r.error) {
      await closeOffscreen();
      return {
        error: (r && r.error) || "The recorder did not answer",
        needsMic: Boolean(r && r.needsMic),
      };
    }

    await setState({ recording: true, recordingTabId: tabId, stopping: false });
    chrome.action.setBadgeText({ text: "REC" });
    chrome.action.setBadgeBackgroundColor({ color: "#d32f2f" });

    return { ok: true };
  } catch (err) {
    await closeOffscreen();
    return { error: err.message };
  }
}

async function handleStop() {
  const state = await getState();
  if (!state.recording) return { error: "Not recording" };
  if (state.stopping) return { error: "Already uploading" };

  await setState({ ...state, stopping: true });
  const settings = await chrome.storage.local.get(["backendUrl", "token"]);

  chrome.runtime.sendMessage({
    action: "offscreen-stop",
    backendUrl: settings.backendUrl || "http://127.0.0.1:8750",
    token: settings.token || "",
  });

  chrome.action.setBadgeText({ text: "..." });
  chrome.action.setBadgeBackgroundColor({ color: "#f9a825" });

  return { ok: true };
}

async function hasOffscreen() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  return contexts.length > 0;
}

async function ensureOffscreen() {
  if (!(await hasOffscreen())) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA"],
      justification: "Recording tab audio for meeting capture",
    });
  }
}

async function closeOffscreen() {
  if (await hasOffscreen()) {
    await chrome.offscreen.closeDocument();
  }
}
