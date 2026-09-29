"""Bake the checked Echooo overlay into an isolated pinned upstream checkout."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
REVISION = '60e885df6f9ed0f38ef141438caac9978a38a6cc'


def prepare(checkout):
    head = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if head != REVISION:
        raise SystemExit('Unexpected Attendee revision.')
    spec = importlib.util.spec_from_file_location('overlay', ROOT / 'deploy/attendee/overlay.py')
    overlay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)
    overlay.build(checkout, checkout)
    for source, target in {
        'cloud/settings.py': 'attendee/settings/echooo.py',
        'bootstrap.py': 'echooo_bootstrap.py',
        'local_debug.py': 'attendee/echooo_debug.py',
        'urls.py': 'attendee/echooo_urls.py',
        'audio_bridge.py': 'attendee/echooo_audio.py',
        'worker.sh': 'echooo-worker.sh',
    }.items():
        shutil.copyfile(ROOT / 'deploy/attendee' / source, checkout / target)


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
