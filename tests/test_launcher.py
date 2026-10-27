"""Offline shell bootstrap tests; native Windows execution is a separate check."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).parents[1]


@pytest.mark.skipif(os.name == 'nt', reason='POSIX launcher test')
def test_shell_first_run_reuse_paths_and_exit_status(tmp_path):
    checkout = tmp_path / 'checkout with spaces'
    checkout.mkdir()
    shutil.copy2(REPO / 'run.sh', checkout)
    tools = tmp_path / 'tools'
    tools.mkdir()
    bootstrap = tools / 'python3'
    bootstrap.write_text(f'#!{sys.executable}\n' + '''
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
with open(os.environ['EE_LAUNCH_LOG'], 'a') as f:
    f.write(json.dumps({'args': args, 'cwd': os.getcwd(), 'utf8': os.environ.get('PYTHONUTF8')}) + '\\n')
if args[:2] == ['-m', 'venv']:
    target = pathlib.Path(args[2]) / 'bin' / 'python'
    target.parent.mkdir(parents=True)
    shutil.copy2(__file__, target)
if args[:2] == ['-m', 'easyeda2kicad_local']:
    sys.exit(int(os.environ.get('EE_APP_EXIT', '0')))
''')
    bootstrap.chmod(0o755)
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
               EE_LAUNCH_LOG=str(tmp_path / 'calls.jsonl'))
    args = [str(checkout / 'run.sh'), 'a link with spaces', NEW_UUID]
    first = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert (checkout / '.venv/.ee2kicad-ready').exists()
    env['EE_APP_EXIT'] = '7'
    second = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert second.returncode == 7
    calls = [json.loads(s) for s in Path(env['EE_LAUNCH_LOG']).read_text().splitlines()]
    assert sum(c['args'][:2] == ['-m', 'venv'] for c in calls) == 1
    assert sum(c['args'][:2] == ['-m', 'pip'] for c in calls) == 1
    launches = [c for c in calls if c['args'][:2] == ['-m', 'easyeda2kicad_local']]
    assert len(launches) == 2
    assert all(c['args'][2:] == args[1:] and c['cwd'] == str(checkout) and c['utf8'] == '1' for c in launches)


NEW_UUID = 'f6ad09a5a9e24d199330c64690aa6c38'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX launcher test')
def test_shell_missing_python(tmp_path):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    shutil.copy2(REPO / 'run.sh', checkout)
    tools = tmp_path / 'tools'
    tools.mkdir()
    (tools / 'dirname').symlink_to(shutil.which('dirname'))
    result = subprocess.run([str(checkout / 'run.sh')], env=dict(os.environ, PATH=str(tools)),
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert len(result.stderr.splitlines()) == 1
    assert 'Python 3.11+' in result.stderr and 'https://www.python.org/downloads/' in result.stderr
