#!/usr/bin/env python3
"""Reproducible local Attendee setup. Secrets never appear in command output."""
import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
REVISION = '60e885df6f9ed0f38ef141438caac9978a38a6cc'
os.chdir(ROOT)

def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)

def prepare():
    LOCAL.mkdir(exist_ok=True)
    env = LOCAL / 'attendee.env'
    if not env.exists():
        values = {'DJANGO_SECRET_KEY': secrets.token_hex(32),
            'CREDENTIALS_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            'POSTGRES_PASSWORD': secrets.token_hex(24), 'ECHOOO_CONNECTOR_KEY': secrets.token_hex(24),
            'ECHOOO_ADMIN_PASSWORD': secrets.token_hex(16)}
        with open(env, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            f.write(''.join(f'{k}={v}\n' for k, v in values.items()))
    tls = LOCAL / 'attendee-tls'
    tls.mkdir(exist_ok=True)
    if not (tls / 'server.crt').exists():
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '365',
            '-keyout', str(tls / 'server.key'), '-out', str(tls / 'server.crt'),
            '-subj', '/CN=echooo-gateway', '-addext', 'subjectAltName=DNS:echooo-gateway',
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (tls / 'server.key').chmod(0o600)

def compose(*args):
    env = os.environ.copy()
    local_settings = {}
    if (ROOT / '.env').exists():
        for line in (ROOT / '.env').read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                local_settings[key.strip()] = value.strip().strip('"\'')
    env.setdefault('ECHOOO_PORT', env.get('APP_PORT', local_settings.get('APP_PORT', '8000')))
    if not env['ECHOOO_PORT'].isdigit() or not 1 <= int(env['ECHOOO_PORT']) <= 65535:
        raise SystemExit('ECHOOO_PORT must be a valid port number.')
    run('docker', 'compose', '-f', 'deploy/attendee/compose.yml', *args, env=env)

def configure():
    values = dict(line.split('=', 1) for line in (LOCAL / 'attendee.env').read_text().splitlines())
    path = ROOT / '.env'
    text = path.read_text() if path.exists() else ''
    updates = {'ATTENDEE_BASE_URL': 'http://127.0.0.1:8011/api/v1',
        'ATTENDEE_API_KEY': values['ECHOOO_CONNECTOR_KEY'], 'ATTENDEE_CALLBACK_URL': 'wss://echooo-gateway:8443'}
    lines = [line for line in text.splitlines() if line.split('=', 1)[0].strip() not in updates]
    path.write_text('\n'.join(lines) + '\n' + ''.join(f'{k}={v}\n' for k, v in updates.items()))
    path.chmod(0o600)

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'up'
    if action not in {'up', 'down', 'status', 'logs'}:
        raise SystemExit('Usage: python3 scripts/attendee.py [up|down|status|logs]')
    if action != 'up':
        compose(*({'down': ['down'], 'status': ['ps'], 'logs': ['logs', '--tail=80']}[action]))
        return
    run('docker', 'info', stdout=subprocess.DEVNULL)
    prepare()
    checkout = LOCAL / 'attendee'
    if not checkout.exists():
        run('git', 'init', str(checkout))
        run('git', '-C', str(checkout), 'remote', 'add', 'origin', 'https://github.com/attendee-labs/attendee.git')
        run('git', '-C', str(checkout), 'fetch', '--depth=1', 'origin', REVISION)
        run('git', '-C', str(checkout), 'checkout', '--detach', 'FETCH_HEAD')
    head = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if head != REVISION or subprocess.check_output(['git', '-C', str(checkout), 'status', '--porcelain'], text=True).strip():
        raise SystemExit('Attendee checkout differs from the pinned revision. Preserve your changes before rebuilding.')
    run('docker', 'build', '--platform', 'linux/amd64', '-t', 'echooo-attendee:60e885df', str(checkout))
    compose('up', '-d', '--wait', 'postgres', 'redis')
    compose('run', '--rm', '--no-deps', '--user', 'root', 'api', 'chown', '1000:1000', '/attendee/local-debug')
    compose('run', '--rm', '--no-deps', 'api', 'python', 'manage.py', 'migrate', '--noinput')
    compose('run', '--rm', '--no-deps', 'api', 'python', 'manage.py', 'shell', '-c', 'exec(open("echooo_bootstrap.py").read())')
    compose('up', '-d', 'api', 'worker', 'echooo-gateway')
    configure()
    print('Attendee is starting at http://127.0.0.1:8011. Restart Echooo to load its connector settings.')
    print('Dashboard login email: echooo@localhost. Password: ECHOOO_ADMIN_PASSWORD in .local/attendee.env.')

if __name__ == '__main__':
    main()
