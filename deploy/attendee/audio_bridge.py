"""Versioned PCM bridge: browser acknowledgements replace chained sleep loops."""
def handle(controller, message):
    if message.get('trigger') != 'echooo.audio':
        return False
    data = message.get('data', {})
    result = {'stream_id': data.get('stream_id'), 'request_id': data.get('request_id')}
    try:
        if data.get('action') not in {'start', 'chunk', 'finish', 'status', 'pause', 'resume', 'stop'}:
            raise ValueError('Invalid audio action')
        if data.get('action') == 'start' and data.get('sample_rate') not in {8000, 16000, 24000}:
            raise ValueError('Invalid sample rate')
        if len(data.get('chunk', '')) > 64000:
            raise ValueError('Audio packet too large')
        reply = controller.adapter.driver.execute_async_script('''
            const data = arguments[0], done = arguments[arguments.length-1];
            window.botOutputManager.echoooAudio(data).then(done).catch(()=>done({error:'Audio playback failed'}));
        ''', data)
        result.update(reply)
    except Exception:
        result['error'] = 'Meeting audio playback failed'
    controller.websocket_client_manager.send_mixed_audio({
        'trigger': 'echooo.audio_status', 'bot_id': controller.bot_in_db.object_id, 'data': result})
    return True
