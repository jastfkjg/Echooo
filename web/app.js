const $ = (id) => document.getElementById(id);

const stateLabels = {
  idle: "未连接",
  connecting: "正在连接",
  listening: "正在聆听",
  thinking: "正在思考",
  speaking: "正在回答",
  interrupting: "正在打断",
  error: "连接异常",
  closed: "已结束",
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

async function loadPublicConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) return;
    const config = await response.json();
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
      option.textContent = device.label || `麦克风 ${index + 1}`;
      $("microphone").append(option);
    });
    if (!microphones.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "默认麦克风";
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
      $("call-label").textContent = "结束会话";
      $("send-debug").disabled = false;
      $("microphone").disabled = true;
      $("pipeline-pill").textContent = "Live";
      $("pipeline-pill").classList.add("active");
      logEvent("ws.connected");
    };
    socket.onmessage = handleMessage;
    socket.onerror = () => showError("WebSocket 连接失败，请检查服务端日志。", false);
    socket.onclose = () => {
      logEvent("ws.closed");
      cleanupCall();
    };
  } catch (error) {
    showError(error.message || "无法启动麦克风。", false);
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
  $("call-button").disabled = false;
  $("call-button").classList.remove("active");
  $("call-label").textContent = "开始会话";
  $("send-debug").disabled = true;
  $("microphone").disabled = false;
  $("pipeline-pill").textContent = "Standby";
  $("pipeline-pill").classList.remove("active");
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
    case "transcript.user.partial":
      partialUser = upsertMessage(partialUser, "user", message.text, true);
      break;
    case "transcript.user.final":
      partialUser?.remove();
      partialUser = null;
      appendMessage("user", message.text, false, message.source === "debug" ? "测试输入" : "语音输入");
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
        liveAssistant.querySelector(".message-head span:last-child").textContent = "已打断";
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
  appendMessage("assistant", "对话记录已从当前页面清空，服务端会话上下文保持不变。", false, "系统");
});
$("clear-events").addEventListener("click", () => {
  $("event-log").innerHTML = '<p class="event-placeholder">事件记录已清空。</p>';
});

if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
  $("call-button").disabled = true;
  showError("当前浏览器不支持 AudioWorklet，请使用最新版 Chrome、Edge 或 Safari。", false);
} else {
  $("microphone").disabled = false;
  loadPublicConfig();
  listMicrophones();
  navigator.mediaDevices.addEventListener?.("devicechange", listMicrophones);
}
