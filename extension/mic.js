const out = document.getElementById("out");

navigator.mediaDevices.getUserMedia({ audio: true }).then(
  (stream) => {
    stream.getTracks().forEach((t) => t.stop());
    out.textContent =
      "Microphone allowed. You can close this tab and start recording.";
  },
  (err) => {
    out.textContent = `Microphone not allowed: ${err.message}. Allow it for this extension in Chrome's site settings, then try again.`;
  },
);
