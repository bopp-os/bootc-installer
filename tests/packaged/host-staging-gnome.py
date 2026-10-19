"""Verify installed helper persistence without home sharing or privilege escalation."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/app/share/org.bootcinstaller.Installer")
from bootc_installer.utils import fisherman_runner as runner

assert runner.__file__.startswith('/app/')
assert runner.IN_FLATPAK
assert runner.CACHE_DIR == os.path.join(os.environ['XDG_CACHE_HOME'], 'bootc-installer')
if sys.argv[1] == 'stage':
    assert runner.stage_on_host(), 'staging must verify the actual host-visible payload'
else:
    assert sys.argv[1] == 'verify'
    # A second sandbox must see the first one's bytes without staging again.
    assert Path(runner.HOST_PATH).is_file()
expected = hashlib.sha256(Path('/app/bin/fisherman').read_bytes()).hexdigest()
assert hashlib.sha256(Path(runner.HOST_PATH).read_bytes()).hexdigest() == expected
host = subprocess.run(['flatpak-spawn', '--host', 'sha256sum', '--', runner.HOST_PATH],
                      check=True, capture_output=True, text=True, timeout=10)
assert host.stdout.split()[0] == expected
# Read-only schema validation proves host execution; never run the install command.
validated = subprocess.run(runner.fisherman_argv() + ['validate', '--json', '--partial', '-'],
                           check=False, input='{"hostname":"packaged-canary"}',
                           capture_output=True, text=True, timeout=10)
assert validated.returncode == 0, validated.stderr
json.loads(validated.stdout)
print(json.dumps({'host_staging': 'pass', 'phase': sys.argv[1],
                  'path': runner.HOST_PATH, 'sha256': expected, 'validation': 'passed'}))
