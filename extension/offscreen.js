let recorder = null;
let chunks = [];
let audioCtx = null;
let inputs = [];

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "offscreen-start") {
    startCapture(message.streamId).then(
      () => sendResponse({ ok: true }),
      (err) =>
        sendResponse({ error: err.message, needsMic: Boolean(err.needsMic) }),
    );
    return true;
  }
  if (message.action === "offscreen-stop") {
    stopCapture(message.backendUrl, message.token);
  }
});

async function startCapture(streamId) {
  if (recorder) throw new Error("Already recording");

  // This page is hidden, so it cannot show Chrome's prompt, and asking anyway counts as a
  // refusal. Look the permission up first; the visible mic.html page is what asks.
  const { state } = await navigator.permissions.query({ name: "microphone" });
  if (state !== "granted") {
    const failure = new Error("Shelby needs the microphone to record your own voice");
    failure.needsMic = true;
    throw failure;
  }

  const tab = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
  });

  // The tab only plays what the others say. The user's own voice goes out through the
  // microphone and never comes back through the tab, so it has to be recorded separately.
  let mic;
  try {
    mic = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    tab.getTracks().forEach((t) => t.stop());
    const denied = err.name === "NotAllowedError";
    const failure = new Error(
      denied ? "Shelby needs the microphone to record your own voice" : err.message,
    );
    failure.needsMic = denied;
    throw failure;
  }
  inputs = [tab, mic];

  audioCtx = new AudioContext();
  const tabSource = audioCtx.createMediaStreamSource(tab);
  // Reconnect audio to speakers so the user still hears the call
  tabSource.connect(audioCtx.destination);

  // One recording with the tab and the microphone mixed together
  const mix = audioCtx.createMediaStreamDestination();
  tabSource.connect(mix);
  audioCtx.createMediaStreamSource(mic).connect(mix);

  chunks = [];
  recorder = new MediaRecorder(mix.stream, { mimeType: "audio/webm;codecs=opus" });
  recorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };
  recorder.start(1000);
}

async function stopCapture(backendUrl, token) {
  if (!recorder) {
    chrome.runtime.sendMessage({
      action: "upload-error",
      error: "Nothing is recording",
    });
    return;
  }

  return new Promise((resolve) => {
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: "audio/webm" });
      chunks = [];

      if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
      }

      // The recorder now reads a mix, so the tab and the microphone must be released themselves
      inputs.forEach((s) => s.getTracks().forEach((t) => t.stop()));
      inputs = [];
      recorder = null;

      const ts = new Date()
        .toISOString()
        .replace(/[:.]/g, "-")
        .slice(0, 19);
      const name = `meeting-${ts}.webm`;
      const url = `${backendUrl}/api/uploads/audio?name=${encodeURIComponent(name)}`;

      try {
        const resp = await fetch(url, {
          method: "PUT",
          headers: {
            "x-assistant-token": token,
            "Content-Type": "audio/webm",
          },
          body: blob,
        });

        if (!resp.ok) throw new Error(`Upload failed: ${resp.status}`);

        const result = await resp.json();
        chrome.runtime.sendMessage({ action: "upload-complete", result });
      } catch (err) {
        chrome.runtime.sendMessage({
          action: "upload-error",
          error: err.message,
        });
      }

      resolve();
    };

    recorder.stop();
  });
}
