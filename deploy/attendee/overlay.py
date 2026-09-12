"""Apply small, checked adaptations to a COPY of the pinned Attendee sources."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    'bots/zoom_web_bot_adapter/zoom_web_chromedriver_page.js',
    'bots/web_bot_adapter/shared_chromedriver_payload.js',
    'bots/bot_controller/bot_controller.py',
    'bots/bot_controller/realtime_audio_output_manager.py',
]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Attendee overlay anchor changed; review compatibility before upgrading.')
    return text.replace(old, new, 1)


def build(checkout=None, output=None):
    checkout = checkout or ROOT / '.local/attendee'
    output = output or ROOT / '.local/attendee-overlay'
    texts = {f: (checkout / f).read_text() for f in FILES}
    name = FILES[0]
    texts[name] = (ROOT / 'deploy/attendee/zoom-chat.js').read_text() + '\n' + replace_once(texts[name],
        "        console.log('onReceiveChatMsg', chatMessage);", '')
    texts[name] = replace_once(texts[name], """window.ws.sendJson({
                type: 'ChatMessage',
                message_uuid: chatMessage.content.messageId,
                participant_uuid: chatMessage.senderId.toString(),
                timestamp: Math.floor(parseInt(chatMessage.content.t) / 1000),
                text: chatMessage.content.text,
            });""", "window.ws.sendJson(echoooZoomChat(chatMessage, window.userManager.allUsersMap));")
    texts[name] = replace_once(texts[name], 'window.participantSpeechStartStopManager?.addActiveSpeaker(activeSpeaker.userId);',
        'window.participantSpeechStartStopManager?.sendSpeechStartStopEvent(activeSpeaker.userId, true, Date.now());')
    name = FILES[1]
    texts[name] = replace_once(texts[name], '    async playPCMAudio(pcmData,', '''    stopPCMAudio() {
        clearTimeout(this.echoooProcessTimer);
        clearTimeout(this.turnOffMicTimeout);
        this.turnOffMicTimeout = null;
        this.audioQueue = [];
        this.isPlayingAudioQueue = false;
        this.nextPlayTime = 0;
        for (const source of this.echoooSources || []) {
            try { source.stop(); source.disconnect(); } catch (_) {}
        }
        this.echoooSources?.clear();
        this.disableMic();
    }

    async playPCMAudio(pcmData,''')
    texts[name] = replace_once(texts[name], '        source.start(this.nextPlayTime);', '''        this.echoooSources ||= new Set();
        this.echoooSources.add(source);
        source.onended = () => { this.echoooSources.delete(source); source.disconnect(); };
        source.start(this.nextPlayTime);''')
    texts[name] = replace_once(texts[name], '        setTimeout(\n            () => this._processAudioQueue(),',
        '        this.echoooProcessTimer = setTimeout(\n            () => this._processAudioQueue(),')
    texts[name] = replace_once(texts[name], '        this.gainNode.connect(this.audioContext.destination); // This causes it to play through the speakers',
        '        // Echooo sends speech only to the virtual microphone.')
    texts[name] += '\n' + (ROOT / 'deploy/attendee/streaming-audio.js').read_text() + '\ninstallEchoooStreamingAudio(BotOutputManager);\n'
    name = FILES[2]
    texts[name] = replace_once(texts[name], '            message = json.loads(message_json)\n', '''            message = json.loads(message_json)
            from attendee.echooo_audio import handle
            if handle(self, message):
                return
            if message.get("trigger") == "echooo.audio_stop":
                self.realtime_audio_output_manager.cleanup()
                if getattr(self.adapter, "driver", None):
                    self.adapter.driver.execute_script("window.botOutputManager.stopPCMAudio();")
                return
''')
    texts[name] = replace_once(texts[name], '        # Mirror participant joins/leaves into the LiveKit room if room sync is enabled', '''        if self.websocket_client_manager and event["event_type"] in (ParticipantEventTypes.SPEECH_START, ParticipantEventTypes.SPEECH_STOP):
            self.websocket_client_manager.send_mixed_audio({"trigger": "echooo.speaker", "bot_id": self.bot_in_db.object_id, "data": {
                "participant_uuid": str(participant["participant_uuid"]), "is_self": participant["participant_is_the_bot"],
                "active": event["event_type"] == ParticipantEventTypes.SPEECH_START, "timestamp_ms": event["timestamp_ms"]}})

        # Mirror participant joins/leaves into the LiveKit room if room sync is enabled''')
    name = FILES[3]
    texts[name] = replace_once(texts[name], '            return chunk, sample_rate', '            return chunk')
    texts[name] = replace_once(texts[name], '        self.stop_audio_thread = True\n',
        '        self.stop_audio_thread = True\n        self.inner_chunk_buffer = b""\n')
    for name, content in texts.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return output


if __name__ == '__main__':
    build()
    print('Prepared the Echooo chat routing and audio interruption overlay.')
