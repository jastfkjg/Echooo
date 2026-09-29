"""Persist connector secrets and patch only Echooo's three connector settings."""
import base64
import os
from pathlib import Path
import secrets
import sys


def write_private(path, content):
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    temporary.chmod(0o600)
    temporary.replace(path)


def prepare(home):
    directory = home / 'attendee'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / 'attendee.env'
    if not path.exists():
        values = {name: secrets.token_hex(32) for name in (
            'DJANGO_SECRET_KEY', 'POSTGRES_PASSWORD', 'ECHOOO_CONNECTOR_KEY', 'ECHOOO_ADMIN_PASSWORD')}
        values['CREDENTIALS_ENCRYPTION_KEY'] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        write_private(path, ''.join('{}={}\n'.format(k, v) for k, v in values.items()))


def connect(home):
    values = dict(line.split('=', 1) for line in (home / 'attendee/attendee.env').read_text().splitlines())
    updates = {'ATTENDEE_BASE_URL': 'http://attendee-api:8000/api/v1',
               'ATTENDEE_API_KEY': values['ECHOOO_CONNECTOR_KEY'],
               'ATTENDEE_CALLBACK_URL': 'wss://echooo-attendee-gateway:8443'}
    path = home / 'app.env'
    lines = [line for line in path.read_text().splitlines()
             if line.split('=', 1)[0].strip().replace('export ', '', 1).strip() not in updates]
    write_private(path, '\n'.join(lines) + '\n' + ''.join('{}={}\n'.format(k, v) for k, v in updates.items()))


if __name__ == '__main__':
    {'prepare': prepare, 'connect': connect}[sys.argv[1]](Path('/opt/echooo'))
