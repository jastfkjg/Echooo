"""Verify trusted TLS, Docker routing and WebSocket forwarding without a real bot."""
import http.client
import ssl

connection = http.client.HTTPSConnection('echooo-attendee-gateway', 8443,
    context=ssl.create_default_context(cafile='/echooo-ca.crt'), timeout=15)
connection.request('GET', '/ws/meeting-bots/deployment-probe?token=invalid', headers={
    'Connection': 'Upgrade', 'Upgrade': 'websocket', 'Sec-WebSocket-Version': '13',
    'Sec-WebSocket-Key': 'ZWNob29vLWRlcGxveS1jaA==',
})
response = connection.getresponse()
assert response.status == 403, 'Expected Echooo to reject the unauthenticated WebSocket, got {}'.format(response.status)
connection.close()
print('Private TLS WebSocket callback routing passed.')
