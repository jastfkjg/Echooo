# Echooo

Echooo is a provider-neutral realtime voice-agent foundation for the AssemblyAI
hackathon. Speech recognition, orchestration, language-model inference, and speech
synthesis are isolated behind small interfaces so each service can be replaced without
rewriting the browser application.

The local demo requires no credentials. It includes a deterministic mock LLM and a
generated audio tone to verify the complete WebSocket and playback path.

## Architecture

```text
Browser microphone (mono PCM16)
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
             LanguageModelProvider --> streaming LLM API
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

Provider contracts live in [`src/echooo/providers/base.py`](src/echooo/providers/base.py).
Concrete implementations are selected in
[`src/echooo/providers/factory.py`](src/echooo/providers/factory.py). Per-session voice
choices use the shared `VoiceProfile` model and are not deployment environment settings.

## Run the zero-credential demo

Requirements: Python 3.11+ and a current Chrome, Edge, or Safari release.

```bash
cd /Users/zilong/Developer/projects/echooo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.mock.example .env
python -m echooo
```

If a configured package mirror cannot find `setuptools`, retry the install against the
official index without changing global pip settings:

```bash
PIP_INDEX_URL=https://pypi.org/simple python -m pip install -e '.[dev]'
```

Open <http://127.0.0.1:8000>, select **Start session**, and grant microphone access.
Mock STT ignores microphone audio; use **Test message** to exercise the LLM, sentence
segmentation, TTS, binary WebSocket, and browser playback path. The health endpoint is
available at <http://127.0.0.1:8000/health>.

## Connect AssemblyAI Realtime STT

Create the real-service configuration and add the API key:

```bash
cp .env.example .env
```

```dotenv
STT_PROVIDER=assemblyai
ASSEMBLYAI_API_KEY=...
ASSEMBLYAI_SPEECH_MODEL=universal-3-5-pro
```

The browser sends mono PCM16 in 100 ms frames at 16 kHz. The adapter emits partial and
final `Turn` events, uses `SpeechStarted` for barge-in, and updates `agent_context` after
completed assistant turns.

No language is pinned in configuration. Universal-3.5 Pro determines the spoken
language and supports code-switching within a session. The LLM system instruction also
requires replies to follow the language of the user's latest message.

For the first live test, keep `LLM_PROVIDER=mock` and `TTS_PROVIDER=mock` so STT can be
verified independently.

## Connect an LLM

The included adapter works with a streaming OpenAI-compatible `/chat/completions` route,
including OpenAI, vLLM, and compatible local servers:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=...
LLM_MODEL=your-model-name
```

For a trusted local endpoint, change `LLM_BASE_URL`; the key may be empty if the server
does not require one. Agent behavior is versioned in `config/prompts.toml`, not `.env`.

## Connect CosyVoice

Install CosyVoice separately on a GPU machine and download a compatible checkpoint by
following its official README:

```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
# Create the documented Python 3.10 environment and download a checkpoint.
python runtime/python/fastapi/server.py \
  --port 50000 \
  --model_dir pretrained_models/your-cosyvoice-model
```

Echooo only needs the service connection and output format in `.env`:

```dotenv
TTS_PROVIDER=cosyvoice
COSYVOICE_BASE_URL=http://127.0.0.1:50000
COSYVOICE_SAMPLE_RATE=24000
COSYVOICE_TIMEOUT_SECONDS=60
```

Speaker identity, synthesis mode, reference audio, reference transcript, and style
instruction are selected from the **Voice profile** panel in the browser. Supported UI
modes are:

- **Preset speaker:** enter a speaker ID exposed by the selected SFT checkpoint.
- **Custom voice sample:** upload reference audio and enter its exact transcript for
  zero-shot synthesis.
- **Styled voice sample:** upload reference audio and provide a natural-language style
  instruction for `instruct2` synthesis.

Accepted uploads are WAV, MP3, FLAC, M4A, and OGG files up to 10 MB. Uploaded voice
biometrics are held in process memory, are never written to disk, and are removed when
the voice session closes. Only use a voice that you own or have explicit permission to
clone.

The CosyVoice adapter also retains backend support for `cross_lingual` and `instruct`
profiles. It expects the official FastAPI server to return raw mono PCM16 audio. Set
`COSYVOICE_SAMPLE_RATE` to the actual output rate of the selected checkpoint.

When CosyVoice runs on another host or container, use a hostname or private IP reachable
from the Echooo process instead of `127.0.0.1`.

## Recommended integration order

1. Run all three mock providers and submit a test message.
2. Enable only AssemblyAI and verify multilingual transcripts and turn boundaries.
3. Enable the real LLM while keeping mock TTS; verify language matching and streaming.
4. Enable a CosyVoice preset speaker.
5. Test custom sample upload and zero-shot synthesis.
6. Test interruption, silence, noise, rapid follow-up turns, and code-switching.

This sequence keeps failures attributable to one service instead of three remote systems.

## Replace a provider

1. Implement one interface from `src/echooo/providers/base.py`.
2. Normalize output to the shared models in `src/echooo/models.py`.
3. Add a factory branch in `src/echooo/providers/factory.py`.
4. Add protocol and request-mapping tests.

STT implementations return normalized turn events, LLM implementations stream text
deltas, and TTS implementations return mono PCM16 `AudioChunk` objects. Providers that
return MP3 or Opus should decode server-side or introduce an explicit codec protocol.

## Test and inspect

```bash
source .venv/bin/activate
pytest -q
python -m compileall -q src tests
node --check web/app.js
```

The inspector shows active providers, first-token and first-audio latency, turn count,
interruptions, voice-profile status, and key WebSocket events. Secrets are never exposed
through `/api/config` or `session.ready` messages.

## Production notes

- Microphone capture requires HTTPS except on localhost. Use a reverse proxy that
  supports WebSocket upgrades and serve the browser over `wss://`.
- Keep AssemblyAI and LLM keys server-side.
- Protect `/api/voice-samples` with authentication and rate limiting before public use.
- Consider encrypting samples in a dedicated expiring object store when running multiple
  processes; the included in-memory store is intentionally single-process.
- Add request IDs, structured logs, per-provider timeouts, and abuse controls.
- Keep the sample CosyVoice FastAPI server behind a private network or authenticated
  gateway.
- Use sticky WebSocket sessions because provider streams and conversation state live in
  one process for the duration of a call.

## Strong hackathon directions

A generic voice assistant demonstrates infrastructure but is not enough differentiation
on its own. Build one memorable capability above this transport layer:

- **Voice workflow runner:** create a visible plan, confirm side effects, execute tools,
  and narrate progress while remaining interruptible.
- **Consent-based memory:** let users inspect, correct, export, and delete remembered
  information.
- **Adaptive speaking:** adjust answer length, turn timing, and synthesis style from
  interruption rate and speaking pace.

Track task completion, time to first audio, interruption recovery, transcription
corrections, and voice-profile application failures. These metrics make the project more
defensible than a microphone attached to a general chatbot.

## Upstream references

- [AssemblyAI raw v3 streaming WebSocket guide](https://www.assemblyai.com/blog/raw-websocket-voice-agent-with-assemblyai-universal-3-pro-streaming)
- [AssemblyAI streaming documentation](https://www.assemblyai.com/docs/streaming)
- [CosyVoice repository and installation guide](https://github.com/QwenAudio/CosyVoice)
- [CosyVoice official FastAPI server](https://github.com/QwenAudio/CosyVoice/blob/main/runtime/python/fastapi/server.py)
