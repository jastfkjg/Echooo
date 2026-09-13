// Zoom Meeting SDK 5.1.4 emits receiverId on onReceiveChatMsg. Zero is
// serialized as "" by the SDK; accept that only with its explicit Everyone label.
// Unknown recipients remain private in Attendee and are not answered by Echooo.
function echoooZoomChat(message, users) {
    const sender = String(message.senderId ?? '');
    const recipient = message.receiverId;
    const self = [...users.values()].find(user => user.isCurrentUser);
    const selfId = self ? String(self.deviceId) : '';
    const isSelf = !!selfId && sender === selfId;
    let audience = 'unknown';
    if (recipient === 0 || recipient === '0' ||
        (recipient === '' && message.receiver === 'Everyone')) audience = 'public';
    else if (selfId && String(recipient) === selfId) audience = 'private';
    return {
        type: 'ChatMessage',
        message_uuid: message.content.messageId,
        participant_uuid: sender,
        timestamp: Math.floor(Number(message.content.t) / 1000),
        text: message.content.text,
        to_bot: audience !== 'public',
        additional_data: {echooo_audience: audience, echooo_is_self: isSelf},
    };
}
if (typeof module !== 'undefined') module.exports = {echoooZoomChat};
