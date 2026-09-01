const $ = (id) => document.getElementById(id);

const stateLabels = {
  idle: "Disconnected",
  connecting: "Connecting",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  interrupting: "Interrupting",
  error: "Connection error",
  closed: "Ended",
};

let socket = null;
let captureContext = null;
let playbackContext = null;
let captureNode = null;
let captureSink = null;
let playbackNode = null;
let microphoneStream = null;
let timer = null;
let callStartedAt = 0;
let connected = false;
let userTurns = 0;
let interruptions = 0;
let partialUser = null;
let liveAssistant = null;
let activeGeneration = null;
let inputSampleRate = 16000;
let publicConfig = null;
let pendingVoiceProfile = null;
let voiceSampleId = "";
let uploadedFileKey = "";

async function loadPublicConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) return;
    const config = await response.json();
    publicConfig = config;
    inputSampleRate = Number(config.audio?.input_sample_rate) || inputSampleRate;
    if (config.providers) {
      $("provider-stt").textContent = config.providers.stt || "—";
      $("provider-llm").textContent = config.providers.llm || "—";
      $("provider-tts").textContent = config.providers.tts || "—";
    }
  } catch {
    // The WebSocket will surface a clear error if the server is unavailable.
  }
}

function websocketURL() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws`;
}

async function listMicrophones() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const microphones = devices.filter((device) => device.kind === "audioinput");
    const selected = $("microphone").value;
    $("microphone").replaceChildren();
    microphones.forEach((device, index) => {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `Microphone ${index + 1}`;
      $("microphone").append(option);
    });
    if (!microphones.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Default microphone";
      $("microphone").append(option);
    }
    if ([...$("microphone").options].some((option) => option.value === selected)) {
      $("microphone").value = selected;
    }
  } catch {
    // Labels remain unavailable until permission is granted.
  }
}

async function startCall() {
  $("call-button").disabled = true;
  setState("connecting");
  try {
    await loadPublicConfig();
    pendingVoiceProfile = await prepareVoiceProfile();
    const constraints = {
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: false,
        autoGainControl: false,
        ...($("microphone").value ? { deviceId: { ideal: $("microphone").value } } : {}),
      },
    };
    microphoneStream = await navigator.mediaDevices.getUserMedia(constraints);
    await listMicrophones();

    captureContext = new AudioContext();
    playbackContext = new AudioContext();
    await Promise.all([captureContext.resume(), playbackContext.resume()]);
    await Promise.all([
      captureContext.audioWorklet.addModule("/static/capture-worklet.js"),
      playbackContext.audioWorklet.addModule("/static/playback-worklet.js"),
    ]);

    captureNode = new AudioWorkletNode(captureContext, "pcm16-capture", {
      processorOptions: {
        targetSampleRate: inputSampleRate,
        chunkSamples: Math.max(1, Math.round(inputSampleRate / 10)),
      },
    });
    playbackNode = new AudioWorkletNode(playbackContext, "pcm16-playback");
    playbackNode.connect(playbackContext.destination);
    captureSink = captureContext.createGain();
    captureSink.gain.value = 0;
    captureContext
      .createMediaStreamSource(microphoneStream)
      .connect(captureNode)
      .connect(captureSink)
      .connect(captureContext.destination);

    socket = new WebSocket(websocketURL());
    socket.binaryType = "arraybuffer";
    captureNode.port.onmessage = ({ data }) => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(data);
    };
    socket.onopen = () => {
      connected = true;
      callStartedAt = Date.now();
      timer = window.setInterval(updateElapsed, 1000);
      updateElapsed();
      $("call-button").disabled = false;
      $("call-button").classList.add("active");
      $("call-label").textContent = "End session";
      $("send-debug").disabled = false;
      $("microphone").disabled = true;
      $("pipeline-pill").textContent = "Live";
      $("pipeline-pill").classList.add("active");
      sendVoiceProfile(pendingVoiceProfile);
      logEvent("ws.connected");
    };
    socket.onmessage = handleMessage;
    socket.onerror = () => showError("WebSocket connection failed. Check the server logs.", false);
    socket.onclose = () => {
      logEvent("ws.closed");
      cleanupCall();
    };
  } catch (error) {
    showError(error.message || "Unable to start the microphone.", false);
    cleanupCall();
  }
}

async function stopCall() {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "session.end" }));
    window.setTimeout(() => socket?.close(), 200);
  }
  cleanupCall();
}

function cleanupCall() {
  connected = false;
  window.clearInterval(timer);
  timer = null;
  microphoneStream?.getTracks().forEach((track) => track.stop());
  captureNode?.disconnect();
  captureSink?.disconnect();
  playbackNode?.port.postMessage({ type: "stop" });
  playbackNode?.disconnect();
  captureContext?.close();
  playbackContext?.close();
  microphoneStream = captureNode = captureSink = playbackNode = captureContext = playbackContext = null;
  socket = null;
  voiceSampleId = "";
  uploadedFileKey = "";
  pendingVoiceProfile = null;
  $("call-button").disabled = false;
  $("call-button").classList.remove("active");
  $("call-label").textContent = "Start session";
  $("send-debug").disabled = true;
  $("microphone").disabled = false;
  $("pipeline-pill").textContent = "Standby";
  $("pipeline-pill").classList.remove("active");
  setVoiceStatus("Not applied");
  setState("idle");
}

function handleMessage(event) {
  if (event.data instanceof ArrayBuffer) {
    if (event.data.byteLength % 2 === 0) {
      playbackNode?.port.postMessage({ type: "audio", buffer: event.data }, [event.data]);
    }
    return;
  }

  const message = JSON.parse(event.data);
  if (!["transcript.assistant.delta", "transcript.user.partial"].includes(message.type)) {
    logEvent(message.type, message.state || message.name || message.reason || "");
  }

  switch (message.type) {
    case "session.ready":
      $("provider-stt").textContent = message.providers.stt;
      $("provider-llm").textContent = message.providers.llm;
      $("provider-tts").textContent = message.providers.tts;
      break;
    case "session.state":
      setState(message.state);
      break;
    case "session.error":
      showError(message.message, message.recoverable);
      break;
    case "voice.configured":
      setVoiceStatus(`Applied · ${formatVoiceMode(message.mode)}`, "ready");
      break;
    case "voice.error":
      setVoiceStatus("Needs attention", "error");
      showError(message.message, true);
      break;
    case "transcript.user.partial":
      partialUser = upsertMessage(partialUser, "user", message.text, true);
      break;
    case "transcript.user.final":
      partialUser?.remove();
      partialUser = null;
      appendMessage("user", message.text, false, message.source === "debug" ? "Test input" : "Voice input");
      userTurns += 1;
      $("metric-turns").textContent = String(userTurns);
      liveAssistant = null;
      break;
    case "transcript.assistant.delta":
      if (activeGeneration !== message.generation) {
        activeGeneration = message.generation;
        liveAssistant = null;
      }
      liveAssistant = upsertMessage(
        liveAssistant,
        "assistant",
        `${liveAssistant?.dataset.text || ""}${message.text}`,
        true,
      );
      break;
    case "transcript.assistant.final":
      if (liveAssistant) {
        liveAssistant.classList.remove("partial");
        liveAssistant.querySelector(".message-body").textContent = message.text;
        liveAssistant.dataset.text = message.text;
      } else if (message.text) {
        appendMessage("assistant", message.text);
      }
      liveAssistant = null;
      break;
    case "audio.start":
      playbackNode?.port.postMessage({ type: "config", sampleRate: message.sample_rate });
      break;
    case "playback.stop":
      playbackNode?.port.postMessage({ type: "stop" });
      interruptions += 1;
      $("metric-interruptions").textContent = String(interruptions);
      if (liveAssistant) {
        liveAssistant.classList.remove("partial");
        liveAssistant.querySelector(".message-head span:last-child").textContent = "Interrupted";
        liveAssistant = null;
      }
      break;
    case "metric":
      if (message.name === "llm_first_token_ms") $("metric-llm").textContent = formatMs(message.value);
      if (message.name === "tts_first_audio_ms") $("metric-tts").textContent = formatMs(message.value);
      break;
    default:
      break;
  }
}

function appendMessage(role, text, partial = false, source = "") {
  $("empty-state")?.remove();
  const article = document.createElement("article");
  article.className = `message ${role}${partial ? " partial" : ""}`;
  article.dataset.text = text;
  const head = document.createElement("div");
  head.className = "message-head";
  const who = document.createElement("span");
  who.textContent = role === "user" ? "You" : "Echooo";
  const detail = document.createElement("span");
  detail.textContent = source || new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;
  head.append(who, detail);
  article.append(head, body);
  $("transcript").append(article);
  $("transcript").scrollTop = $("transcript").scrollHeight;
  return article;
}

function upsertMessage(element, role, text, partial) {
  if (!element || !element.isConnected) return appendMessage(role, text, partial);
  element.dataset.text = text;
  element.querySelector(".message-body").textContent = text;
  $("transcript").scrollTop = $("transcript").scrollHeight;
  return element;
}

function sendDebugText() {
  const text = $("debug-text").value.trim();
  if (!text || socket?.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "debug.user_text", text }));
  $("debug-text").value = "";
  $("debug-text").focus();
}

function formatVoiceMode(mode) {
  return {
    sft: "Preset",
    zero_shot: "Custom",
    instruct2: "Styled",
  }[mode] || mode;
}

function setVoiceStatus(text, state = "") {
  const status = $("voice-status");
  status.textContent = text;
  if (state) status.dataset.state = state;
  else delete status.dataset.state;
}

function updateVoiceFields() {
  const mode = $("voice-mode").value;
  $("speaker-fields").hidden = mode !== "sft";
  $("sample-fields").hidden = mode === "sft";
  $("voice-transcript-label").hidden = mode !== "zero_shot";
  $("voice-transcript").hidden = mode !== "zero_shot";
  $("instruction-fields").hidden = mode !== "instruct2";
  setVoiceStatus("Not applied");
}

async function uploadVoiceSample(file) {
  const key = `${file.name}:${file.size}:${file.lastModified}`;
  if (voiceSampleId && uploadedFileKey === key) return voiceSampleId;

  setVoiceStatus("Uploading…");
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/voice-samples", { method: "POST", body: form });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || "Voice sample upload failed");
  voiceSampleId = result.id;
  uploadedFileKey = key;
  return voiceSampleId;
}

async function prepareVoiceProfile() {
  const mode = $("voice-mode").value;
  const strict = publicConfig?.providers?.tts === "cosyvoice";
  const profile = {
    mode,
    speaker_id: $("voice-speaker").value.trim(),
    sample_id: "",
    reference_text: $("voice-transcript").value.trim(),
    instruction: $("voice-instruction").value.trim(),
  };

  if (mode === "sft") {
    if (strict && !profile.speaker_id) {
      throw new Error("Enter a speaker ID exposed by the CosyVoice checkpoint.");
    }
    return profile;
  }

  const file = $("voice-file").files[0];
  if (file) profile.sample_id = await uploadVoiceSample(file);
  else profile.sample_id = voiceSampleId;
  if (strict && !profile.sample_id) throw new Error("Choose a reference audio file.");
  if (strict && mode === "zero_shot" && !profile.reference_text) {
    throw new Error("Enter the exact transcript of the reference audio.");
  }
  if (strict && mode === "instruct2" && !profile.instruction) {
    throw new Error("Enter a style instruction for the selected mode.");
  }
  return profile;
}

function sendVoiceProfile(profile) {
  if (!profile || socket?.readyState !== WebSocket.OPEN) return;
  setVoiceStatus("Applying…");
  socket.send(JSON.stringify({ type: "session.configure", voice: profile }));
}

async function applyVoice(event) {
  event.preventDefault();
  const button = $("apply-voice");
  button.disabled = true;
  $("voice-form").setAttribute("aria-busy", "true");
  try {
    pendingVoiceProfile = await prepareVoiceProfile();
    if (socket?.readyState === WebSocket.OPEN) sendVoiceProfile(pendingVoiceProfile);
    else setVoiceStatus("Ready for session", "ready");
  } catch (error) {
    setVoiceStatus("Needs attention", "error");
    showError(error.message || "Unable to apply the voice profile.", true);
  } finally {
    button.disabled = false;
    $("voice-form").removeAttribute("aria-busy");
  }
}

function setState(state) {
  const connection = document.querySelector(".connection");
  connection.dataset.state = state;
  $("status-label").textContent = stateLabels[state] || state;
}

function showError(message, recoverable) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  window.setTimeout(() => { $("toast").hidden = true; }, 6000);
  if (!recoverable) setState("error");
}

function logEvent(type, detail = "") {
  $("event-log").querySelector(".event-placeholder")?.remove();
  const row = document.createElement("div");
  row.className = "event-item";
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });
  const value = document.createElement("span");
  value.textContent = detail ? `${type} · ${detail}` : type;
  value.title = value.textContent;
  row.append(time, value);
  $("event-log").append(row);
  while ($("event-log").children.length > 80) $("event-log").firstElementChild.remove();
  $("event-log").scrollTop = $("event-log").scrollHeight;
}

function updateElapsed() {
  const seconds = Math.max(0, Math.floor((Date.now() - callStartedAt) / 1000));
  $("elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatMs(value) {
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

$("call-button").addEventListener("click", () => connected ? stopCall() : startCall());
$("send-debug").addEventListener("click", sendDebugText);
$("debug-text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.isComposing) sendDebugText();
});
$("clear-transcript").addEventListener("click", () => {
  $("transcript").replaceChildren();
  appendMessage("assistant", "The visible transcript was cleared. Server-side conversation context is unchanged.", false, "System");
});
$("clear-events").addEventListener("click", () => {
  $("event-log").innerHTML = '<p class="event-placeholder">Event history cleared.</p>';
});
$("voice-form").addEventListener("submit", applyVoice);
$("voice-mode").addEventListener("change", updateVoiceFields);
$("voice-file").addEventListener("change", () => {
  voiceSampleId = "";
  uploadedFileKey = "";
  $("voice-file-name").textContent = $("voice-file").files[0]?.name || "No file selected";
  setVoiceStatus("Not applied");
});
updateVoiceFields();

if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
  $("call-button").disabled = true;
  showError("This browser does not support AudioWorklet. Use a current Chrome, Edge, or Safari release.", false);
} else {
  $("microphone").disabled = false;
  loadPublicConfig();
  listMicrophones();
  navigator.mediaDevices.addEventListener?.("devicechange", listMicrophones);
}
