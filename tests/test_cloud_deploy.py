"""Exercise deployment failure boundaries without Docker or cloud credentials."""
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "registry.cn-hangzhou.aliyuncs.com/example/echooo@sha256:" + "a" * 64


@pytest.fixture
def deployment(tmp_path):
    home = tmp_path / "server"
    release = home / "releases" / "new"
    old = home / "releases" / "old"
    release.mkdir(parents=True)
    old.mkdir()
    (home / "current").symlink_to(old)
    for name in ("deploy.env", "app.env"):
        (home / name).write_text("")
    for name in ("deploy.sh", "compose.sh", "validate_config.py"):
        source = (ROOT / "deploy/cloud" / name).read_text()
        (release / name).write_text(source.replace("/opt/echooo", str(home)))
    (release / "preflight.sh").write_text("#!/bin/bash\nexit 0\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
mode = os.environ.get('FAIL_MODE', '')
if 'config' in args and 'json' in args:
    print(json.dumps({'services': {'db': {'environment': {'POSTGRES_PASSWORD': 'a'*64}}, 'app': {'environment': {'PUBLIC_ORIGIN': os.environ.get('TEST_ORIGIN', 'https://example.com'), 'COOKIE_SECURE': os.environ.get('TEST_SECURE', 'true')}}, 'proxy': {'environment': {'DOMAIN': os.environ.get('TEST_DOMAIN', 'example.com'), 'ACME_EMAIL': 'admin@example.com'}}}}))
if 'pull' in args and mode == 'pull': sys.exit(1)
if 'run' in args and mode == 'config': sys.exit(1)
if 'ps' in args and mode in ('existing_db', 'credentials'): print('existing-db-container')
if 'run' in args and mode == 'credentials' and any('create_engine' in a for a in args): sys.exit(1)
if 'pg_dump' in args:
    print('database snapshot')
    if mode == 'backup': sys.exit(1)
if 'up' in args and args[-1] == '180' and mode == 'startup': sys.exit(1)
''')
    docker.chmod(0o755)
    # macOS has no flock. Lock behavior belongs to the Linux utility; these tests
    # exercise script ordering, not the OS lock implementation.
    curl = bin_dir / "curl"
    curl.write_text("#!/usr/bin/env python3\nimport os, pathlib, sys\npath = pathlib.Path(os.environ['CALLS'] + '.curl')\nwith path.open('a') as f:\n    print(' '.join(sys.argv[1:]), file=f)\nif '--retry-all-errors' in sys.argv: sys.exit(2)\nattempt = len(path.read_text().splitlines())\nmode = os.environ.get('FAIL_MODE')\nif mode == 'https' or (mode == 'transient' and attempt < 3): sys.exit(7)\n")
    curl.chmod(0o755)
    for name, body in {"flock": "exit 0", "sleep": "exit 0"}.items():
        path = bin_dir / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], CALLS=str(tmp_path / "calls"))
    return home, release, old, env


def run(deployment, mode="", image=IMAGE):
    home, release, old, env = deployment
    result = subprocess.run(["bash", str(release / "deploy.sh"), image, IMAGE, IMAGE], env=dict(env, FAIL_MODE=mode), capture_output=True, text=True)
    calls_path = Path(env["CALLS"])
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
    return result, calls


def test_success_backs_up_before_starting_and_records_previous(deployment):
    home, release, old, _ = deployment
    result, calls = run(deployment)
    assert result.returncode == 0, result.stderr
    stop = next(i for i, c in enumerate(calls) if 'stop' in c)
    backup = next(i for i, c in enumerate(calls) if 'pg_dump' in c)
    start = next(i for i, c in enumerate(calls) if 'up' in c and c[-1] == '180')
    assert stop < backup < start
    assert (home / 'current').resolve() == release
    assert (home / 'previous').resolve() == old
    assert len(list((home / 'backups').glob('*.dump'))) == 1
    recorded = (release / 'image.env').read_text()
    assert f'POSTGRES_IMAGE={IMAGE}' in recorded
    assert f'CADDY_IMAGE={IMAGE}' in recorded


@pytest.mark.parametrize('mode', ['pull', 'backup', 'startup', 'https'])
def test_failure_does_not_promote_candidate(deployment, mode):
    home, _, old, _ = deployment
    result, calls = run(deployment, mode)
    assert result.returncode != 0
    assert (home / 'current').resolve() == old
    assert not (home / 'previous').exists()
    if mode == 'pull':
        assert not any('stop' in c for c in calls)
    if mode == 'backup':
        assert not any('up' in c and c[-1] == '180' for c in calls)
        assert not list((home / 'backups').iterdir())


def test_rejects_mutable_image_before_touching_docker(deployment):
    result, calls = run(deployment, image='registry.cn-hangzhou.aliyuncs.com/example/echooo:latest')
    assert result.returncode != 0
    assert calls == []


@pytest.mark.parametrize('image', [
    'crpi-demo.cn-hangzhou.personal.cr.aliyuncs.com/example/echooo',
    'demo-registry.cn-hangzhou.cr.aliyuncs.com/example/echooo',
])
def test_accepts_personal_and_enterprise_acr_domains(deployment, image):
    result, _ = run(deployment, image=image + '@sha256:' + 'b' * 64)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('image', [
    'ghcr.io/example/echooo@sha256:' + 'a' * 64,
    'registry.cn-hangzhou.aliyuncs.com/example/echooo:latest',
    "registry.cn-hangzhou.aliyuncs.com/example/echooo'$(id)@sha256:" + 'a' * 64,
])
def test_rejects_wrong_registry_or_unsafe_reference(deployment, image):
    result, calls = run(deployment, image=image)
    assert result.returncode != 0
    assert calls == []


def test_http_ip_deployment_checks_http_without_tls(deployment):
    _, _, _, env = deployment
    env.update(TEST_ORIGIN='http://39.106.102.121', TEST_DOMAIN='39.106.102.121', TEST_SECURE='false')
    result, _ = run(deployment)
    assert result.returncode == 0, result.stderr
    assert 'http://39.106.102.121/health' in Path(env['CALLS'] + '.curl').read_text()


@pytest.mark.parametrize('origin,secure', [('http://example.com', 'true'), ('https://example.com', 'false')])
def test_rejects_cookie_scheme_mismatch_before_downtime(deployment, origin, secure):
    _, _, _, env = deployment
    env.update(TEST_ORIGIN=origin, TEST_SECURE=secure)
    result, calls = run(deployment)
    assert result.returncode != 0
    assert 'COOKIE_SECURE' in result.stderr
    assert not any('stop' in c for c in calls)


def test_public_health_check_recovers_from_transient_connection_errors(deployment):
    home, release, _, env = deployment
    result, _ = run(deployment, mode='transient')
    assert result.returncode == 0, result.stderr
    assert len(Path(env['CALLS'] + '.curl').read_text().splitlines()) == 3
    assert (home / 'current').resolve() == release


def test_public_health_check_stops_after_bounded_retries(deployment):
    home, _, old, env = deployment
    result, _ = run(deployment, mode='https')
    assert result.returncode != 0
    assert 'after 13 attempts' in result.stderr
    assert len(Path(env['CALLS'] + '.curl').read_text().splitlines()) == 13
    assert (home / 'current').resolve() == old


def test_bad_provider_configuration_does_not_stop_running_service(deployment):
    result, calls = run(deployment, mode='config')
    assert result.returncode != 0
    assert not any('stop' in c for c in calls)


def test_existing_database_is_backed_up_before_recreation(deployment):
    result, calls = run(deployment, mode='existing_db')
    assert result.returncode == 0, result.stderr
    backup = next(i for i, c in enumerate(calls) if 'pg_dump' in c)
    assert not any('up' in c for c in calls[:backup])


def test_wrong_database_credentials_fail_before_downtime(deployment):
    result, calls = run(deployment, mode='credentials')
    assert result.returncode != 0
    assert not any('stop' in c for c in calls)
    assert not any('pg_dump' in c for c in calls)
