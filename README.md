# Echooo

Echooo is a small, provider-neutral realtime voice-agent foundation for the AssemblyAI
hackathon. It keeps speech recognition, reasoning, and speech synthesis behind separate
interfaces, so each service can be changed without rewriting the browser or conversation
orchestrator.

The default local mode needs no API key. It uses text input, a deterministic mock LLM,
and a short generated tone to prove the complete WebSocket and audio playback path.

## Architecture

```text
Browser microphone (PCM16, 16 kHz)
          |
          v
FastAPI WebSocket /ws
          |
          +--> SpeechToTextProvider --> AssemblyAI Realtime v3
          |              |
          |        partial/final turns + SpeechStarted
          |              v
          +--> VoiceSession orchestrator
                       |  conversation history
                       |  cancellation / barge-in
                       v
             LanguageModelProvider --> OpenAI-compatible streaming API
                       |
                  text deltas
                       v
              SentenceSegmenter
                       |
                       v
              TextToSpeechProvider --> CosyVoice FastAPI runtime
                       |
                 raw PCM16 audio
                       v
              Browser AudioWorklet
```

Key boundaries are in [`src/echooo/providers/base.py`](src/echooo/providers/base.py).
`VoiceSession` depends only on those interfaces. The concrete providers are selected by
environment variables in [`src/echooo/providers/factory.py`](src/echooo/providers/factory.py).

## 1. Run the zero-credential demo

Requirements: Python 3.11+ and a recent Chrome, Edge, or Safari.

```bash
cd /Users/zilong/Developer/projects/echooo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.mock.example .env
python -m echooo
```

If your configured package mirror reports that it cannot find `setuptools`, retry only
this install with the official index (this does not change global pip settings):

```bash
PIP_INDEX_URL=https://pypi.org/simple python -m pip install -e '.[dev]'
```

Open <http://127.0.0.1:8000>. Click **开始会话**, allow microphone access, then use
the **测试文本** field. Mock STT intentionally ignores microphone audio; the text field
bypasses STT while exercising the same LLM, segmentation, TTS, binary WebSocket, and
browser playback code.

You can also check the server at <http://127.0.0.1:8000/health>.

## 2. Connect AssemblyAI Realtime STT

Copy the real-service configuration and set the key:

```bash
cp .env.example .env
```

At minimum, fill in:

```dotenv
STT_PROVIDER=assemblyai
ASSEMBLYAI_API_KEY=...
ASSEMBLYAI_LANGUAGE_CODE=zh
```

The browser sends mono PCM16 in 100 ms frames at 16 kHz. The adapter connects to the
AssemblyAI v3 streaming WebSocket, emits partial/final `Turn` events, and uses
`SpeechStarted` for barge-in. `agent_context` is updated after a completed assistant turn
to reduce transcription errors caused by the agent's own speech.

`language_code=zh` pins a Mandarin-only session. Leave it empty if users are expected to
code-switch between the languages supported by the selected AssemblyAI model.

For a first live test, keep `LLM_PROVIDER=mock` and `TTS_PROVIDER=mock`. This isolates STT
before adding two more external dependencies.

## 3. Connect an LLM

The included adapter works with a streaming OpenAI-compatible `/chat/completions` route,
including OpenAI, vLLM, and compatible local servers:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=...
LLM_MODEL=your-model-name
```

For a local compatible endpoint, change `LLM_BASE_URL`; the key may be empty if that
trusted local server does not require one. Keep responses short and speech-friendly in
`LLM_SYSTEM_PROMPT`, because long Markdown-heavy answers sound poor when read aloud.

## 4. Start CosyVoice and connect TTS

Clone and install CosyVoice separately on a GPU machine following its official README.
From the CosyVoice repository, start its provided FastAPI runtime. The exact model path
depends on the CosyVoice release and checkpoint you install; a typical launch shape is:

```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
# Create the Python 3.10 environment and download a checkpoint as documented upstream.
python runtime/python/fastapi/server.py \
  --port 50000 \
  --model_dir pretrained_models/your-cosyvoice-model
```

Then configure Echooo. Start with an SFT speaker if your selected checkpoint exposes one:

```dotenv
TTS_PROVIDER=cosyvoice
COSYVOICE_BASE_URL=http://127.0.0.1:50000
COSYVOICE_MODE=sft
COSYVOICE_SPEAKER=中文女
COSYVOICE_SAMPLE_RATE=24000
```

For zero-shot voice cloning:

```dotenv
COSYVOICE_MODE=zero_shot
COSYVOICE_PROMPT_WAV=assets/voice_prompt.wav
COSYVOICE_PROMPT_TEXT=参考录音中确切说出的文本
```

The prompt transcript must match the reference audio. Only clone voices with explicit
permission. Echooo supports the official runtime endpoints `sft`, `zero_shot`,
`cross_lingual`, `instruct`, and `instruct2`. It expects the server response to be raw
mono PCM16; set `COSYVOICE_SAMPLE_RATE` to the checkpoint's actual output rate.

When CosyVoice runs on another host or container, `127.0.0.1` refers to the Echooo host,
so use a reachable private hostname/IP instead.

## Recommended integration order

1. Run all three mock providers and submit a test text.
2. Enable only AssemblyAI; verify partial/final transcripts and turn boundaries.
3. Enable the real LLM while keeping mock TTS; verify streaming and answer length.
4. Enable CosyVoice SFT, then zero-shot only after the basic audio path is stable.
5. Test interruption by speaking while audio is playing, plus silence, background noise,
   rapid follow-up turns, and Chinese/English code-switching.

This order makes failures attributable to one service instead of debugging three remote
systems at once.

## Swapping a provider

To add a new provider:

1. Implement one interface from `src/echooo/providers/base.py`.
2. Normalize its output to the shared models in `src/echooo/models.py`:
   STT events, text deltas, or mono PCM16 `AudioChunk`s.
3. Add one factory branch in `src/echooo/providers/factory.py` and a configuration value.
4. Add a request/protocol mapping test; the orchestrator and browser need no change.

Examples: Deepgram/Azure for STT, a native Anthropic or Responses API adapter for LLM,
and ElevenLabs/Azure Speech for TTS. If a TTS returns MP3/Opus, decode it server-side or
add an explicit browser codec protocol instead of pretending it is PCM16.

## Test and inspect

```bash
source .venv/bin/activate
pytest -q
python -m compileall -q src
```

The right-side console shows provider selection, first-token/first-audio latency, turn
count, interruption count, and key WebSocket events. Server logs contain provider errors.
Secrets are never included in `/api/config` or WebSocket `session.ready` messages.

## Production notes

- Microphone capture requires HTTPS except on localhost. Deploy behind a reverse proxy
  that supports WebSocket upgrades and use `wss://` from the browser.
- Do not put AssemblyAI or LLM keys in frontend code. This project keeps them server-side.
- Add authentication, rate limits, request/session IDs, structured logs, and per-provider
  timeouts before exposing a public endpoint.
- Run CosyVoice behind a private network or authenticated gateway; its sample FastAPI
  server should not be treated as an internet-facing production service.
- Scale with sticky WebSocket sessions because conversation state and provider streams
  live in one process for the duration of a call.

## Strong next directions for the hackathon

The transport layer is now generic; differentiation should live above it. A generic
assistant only demonstrates infrastructure, so give the demo one memorable capability:

- **Voice workflow runner:** the user describes an objective, the agent creates a visible
  plan, asks confirmation before external actions, and narrates progress.
- **Conversation memory with consent:** users can inspect, correct, and delete what the
  assistant remembers, creating a trust-focused voice UX.
- **Adaptive speaking:** use interruption rate and speaking pace to adjust answer length,
  turn silence, and TTS style in real time.

Whichever direction you choose, add a small tool registry with strict schemas and an
approval step for side effects, then record outcome metrics such as task completion,
time-to-first-audio, interruption recovery, and transcription correction rate. That is
substantially more defensible than presenting “a general chatbot with a microphone.”

## Upstream references

- [AssemblyAI raw v3 streaming WebSocket guide](https://www.assemblyai.com/blog/raw-websocket-voice-agent-with-assemblyai-universal-3-pro-streaming)
- [AssemblyAI streaming documentation](https://www.assemblyai.com/docs/streaming)
- [CosyVoice repository and installation guide](https://github.com/QwenAudio/CosyVoice)
- [CosyVoice official FastAPI server](https://github.com/QwenAudio/CosyVoice/blob/main/runtime/python/fastapi/server.py)
