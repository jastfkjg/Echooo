"""Cloud connector secrets, topology and deployment failure boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'deploy/attendee/cloud'
IMAGE = 'registry.cn-hangzhou.aliyuncs.com/example/echooo@sha256:' + 'a' * 64
spec = importlib.util.spec_from_file_location('attendee_configure', SOURCE / 'configure.py')
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


def test_secrets_persist_and_config_patch_preserves_unrelated_values(tmp_path):
    (tmp_path / 'app.env').write_text('# Config\nLLM_API_KEY=unchanged\nATTENDEE_API_KEY=old\nexport ATTENDEE_BASE_URL=http://localhost\n')
    configure.prepare(tmp_path)
    path = tmp_path / 'attendee/attendee.env'
    original = path.read_bytes()
    configure.prepare(tmp_path)
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600
    configure.connect(tmp_path)
    first = (tmp_path / 'app.env').read_text()
    configure.connect(tmp_path)
    assert (tmp_path / 'app.env').read_text() == first
    assert first.startswith('# Config\nLLM_API_KEY=unchanged\n')
    assert first.count('ATTENDEE_API_KEY=') == 1
    assert first.count('ATTENDEE_BASE_URL=') == 1
    assert 'http://attendee-api:8000/api/v1' in first
    assert 'wss://echooo-attendee-gateway:8443' in first
    assert (tmp_path / 'app.env').stat().st_mode & 0o777 == 0o600


def test_network_and_workflow_boundaries():
    config = yaml.safe_load((SOURCE / 'compose.yaml').read_text())
    services = config['services']
    assert services['api']['ports'] == ['127.0.0.1:8011:8000']
    assert all('ports' not in services[s] for s in ('postgres', 'redis', 'gateway', 'worker'))
    assert 'proxy' not in services['worker'].get('networks', {})
    assert services['api']['networks']['proxy']['aliases'] == ['attendee-api']
    assert services['api']['command'][0] == 'gunicorn'
    assert services['api']['environment']['POSTGRES_DB'] == 'attendee'
    assert 'static:/attendee/staticfiles' in services['api']['volumes']
    workflow = yaml.safe_load((ROOT / '.github/workflows/deploy-attendee.yml').read_text())
    existing = yaml.safe_load((ROOT / '.github/workflows/deploy.yml').read_text())
    assert workflow['concurrency'] == existing['concurrency']
    assert 'workflow_dispatch' in workflow.get('on', workflow.get(True))
    for step in workflow['jobs']['deploy']['steps']:
        if step.get('uses') == 'docker/build-push-action@v6':
            assert step['with']['platforms'] == 'linux/amd64'


@pytest.fixture
def deployment(tmp_path):
    home = tmp_path / 'echooo'
    release = home / 'attendee/releases/new'
    old = home / 'attendee/releases/old'
    app = home / 'app-release'
    for directory in (release, old, app):
        directory.mkdir(parents=True)
    for file in SOURCE.glob('*'):
        if file.is_file():
            (release / file.name).write_text(file.read_text().replace('/opt/echooo', str(home)))
    (release / 'preflight.sh').write_text('#!/bin/bash\nexit 0\n')
    (old / 'compose.sh').write_text((release / 'compose.sh').read_text())
    (old / 'image.env').write_text('')
    (home / 'attendee/current').symlink_to(old)
    (app / 'compose.sh').write_text('#!/bin/bash\ndocker compose --project-name echooo "$@"\n')
    (home / 'current').symlink_to(app)
    (home / 'app.env').write_text('LLM_API_KEY=preserve\nATTENDEE_API_KEY=old\n')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    (bindir / 'docker').write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(args) + '\\n')
mode = os.environ.get('FAIL_MODE')
if mode == 'pull' and 'pull' in args: sys.exit(1)
if mode == 'active' and 'exec' in args and 'shell' in args: sys.exit(1)
if 'pg_dump' in args:
    print('snapshot')
    if mode == 'backup': sys.exit(1)
if mode == 'migration' and 'migrate' in args: sys.exit(1)
if mode == 'callback' and 'exec' in args and 'worker' in args: sys.exit(1)
''')
    (bindir / 'openssl').write_text('''#!/usr/bin/env python3
import pathlib, sys
args = sys.argv[1:]
for flag in ('-keyout', '-out'):
    if flag in args: pathlib.Path(args[args.index(flag)+1]).write_text('test certificate')
''')
    (bindir / 'flock').write_text('#!/bin/sh\nexit 0\n')
    for file in bindir.iterdir():
        file.chmod(0o755)
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'], CALLS=str(tmp_path / 'calls'))
    return home, release, old, env


def run(deployment, mode='', image=IMAGE):
    home, release, old, env = deployment
    result = subprocess.run(['bash', str(release / 'deploy.sh'), image, IMAGE, IMAGE, IMAGE],
                            env=dict(env, FAIL_MODE=mode), capture_output=True, text=True)
    path = Path(env['CALLS'])
    calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return result, calls


def test_success_backups_and_promotes_after_verification(deployment):
    home, release, old, _ = deployment
    result, calls = run(deployment)
    assert result.returncode == 0, result.stderr
    backup = next(i for i, c in enumerate(calls) if 'pg_dump' in c)
    migrate = next(i for i, c in enumerate(calls) if 'migrate' in c)
    assert backup < migrate
    assert (home / 'attendee/current').resolve() == release
    assert (home / 'attendee/previous').resolve() == old
    assert 'http://attendee-api:8000/api/v1' in (home / 'app.env').read_text()
    assert list((home / 'attendee/backups').glob('*.dump'))
    assert any('worker' in c and 'exec' in c for c in calls)


@pytest.mark.parametrize('mode', ['pull', 'active', 'backup', 'migration', 'callback'])
def test_failure_keeps_release_and_restores_app_config(deployment, mode):
    home, _, old, _ = deployment
    original = (home / 'app.env').read_bytes()
    result, calls = run(deployment, mode)
    assert result.returncode != 0
    assert (home / 'attendee/current').resolve() == old
    assert (home / 'app.env').read_bytes() == original
    if mode in ('pull', 'active'):
        assert not any('stop' in c for c in calls)
    else:
        assert any('echooo' in c and '--force-recreate' in c for c in calls)
    if mode == 'backup':
        assert not any('migrate' in c for c in calls)


def test_mutable_image_rejected_before_operations(deployment):
    result, calls = run(deployment, image='registry.cn-hangzhou.aliyuncs.com/example/echooo:latest')
    assert result.returncode != 0
    assert not calls


def test_first_deployment(deployment):
    home, release, _, _ = deployment
    (home / 'attendee/current').unlink()
    result, calls = run(deployment)
    assert result.returncode == 0, result.stderr
    assert not any('pg_dump' in c for c in calls)
    assert (home / 'attendee/current').resolve() == release
