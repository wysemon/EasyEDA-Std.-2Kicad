"""Offline shell bootstrap tests; native Windows execution is a separate check."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[1]


@pytest.mark.skipif(os.name == 'nt', reason='POSIX launcher test')
def test_shell_first_run_reuse_paths_and_exit_status(tmp_path):
    checkout = tmp_path / 'checkout with spaces'
    checkout.mkdir()
    shutil.copy2(REPO / 'run.sh', checkout)
    (checkout / 'scripts').mkdir()
    shutil.copy2(REPO / 'scripts/bootstrap.py', checkout / 'scripts')
    (checkout / 'pyproject.toml').write_text('[project]\nname = \"test\"\n')
    tools = tmp_path / 'tools'
    tools.mkdir()
    bootstrap = tools / 'python3'
    bootstrap.write_text(f'#!{sys.executable}\n' + '''
import json, os, pathlib, runpy, shutil, subprocess, sys
args = sys.argv[1:]
with open(os.environ['EE_LAUNCH_LOG'], 'a') as f:
    f.write(json.dumps({'args': args, 'cwd': os.getcwd(), 'utf8': os.environ.get('PYTHONUTF8'), 'caller': os.environ.get('EE2KICAD_CWD')}) + '\\n')
if args[:2] == ['-m', 'venv']:
    target = pathlib.Path(args[2]) / 'bin' / 'python'
    target.parent.mkdir(parents=True)
    shutil.copy2(__file__, target)
if args == ['scripts/bootstrap.py']:
    def install(command, **kwargs):
        with open(os.environ['EE_LAUNCH_LOG'], 'a') as f:
            f.write(json.dumps({'args': command[1:]}) + '\\n')
        return subprocess.CompletedProcess(command, 0)
    subprocess.run = install
    runpy.run_path(args[0], run_name='__main__')
if args[:2] == ['-m', 'easyeda2kicad_local']:
    sys.exit(int(os.environ.get('EE_APP_EXIT', '0')))
''')
    bootstrap.chmod(0o755)
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
               EE_LAUNCH_LOG=str(tmp_path / 'calls.jsonl'))
    args = [str(checkout / 'run.sh'), 'a link with spaces', NEW_UUID]
    first = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    import hashlib
    marker = checkout / '.venv/.ee2kicad-ready'
    assert marker.read_text().strip() == hashlib.sha256((checkout / 'pyproject.toml').read_bytes()).hexdigest()
    env['EE_APP_EXIT'] = '7'
    second = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert second.returncode == 7
    calls = [json.loads(s) for s in Path(env['EE_LAUNCH_LOG']).read_text().splitlines()]
    assert sum(c['args'][:2] == ['-m', 'venv'] for c in calls) == 1
    assert sum(c['args'][:2] == ['-m', 'pip'] for c in calls) == 1
    launches = [c for c in calls if c['args'][:2] == ['-m', 'easyeda2kicad_local']]
    assert len(launches) == 2
    assert all(c['args'][2:] == args[1:] and c['cwd'] == str(checkout) and c['utf8'] == '1' and c['caller'] == str(tmp_path) for c in launches)


    # A dependency declaration change must refresh the package on the next run.
    (checkout / 'pyproject.toml').write_text('[project]\nname = "changed"\n')
    third = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert third.returncode == 7, third.stderr
    calls = [json.loads(s) for s in Path(env['EE_LAUNCH_LOG']).read_text().splitlines()]
    assert sum(c['args'][:2] == ['-m', 'pip'] for c in calls) == 2
    assert sum(c['args'][:2] == ['-m', 'venv'] for c in calls) == 1
    assert marker.read_text().strip() == hashlib.sha256((checkout / 'pyproject.toml').read_bytes()).hexdigest()


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


@pytest.mark.skipif(os.name != 'nt', reason='Requires native Windows CMD and console code pages')
def test_native_windows_caller_codepage_and_exit_status(tmp_path):
    """Use an offline venv and stub app; do not install anything from the network."""
    import hashlib
    import re

    checkout = tmp_path / 'checkout with spaces'
    checkout.mkdir()
    shutil.copy2(REPO / 'run.bat', checkout)
    (checkout / 'scripts').mkdir()
    shutil.copy2(REPO / 'scripts/bootstrap.py', checkout / 'scripts')
    project = checkout / 'pyproject.toml'
    project.write_text('[project]\nname="test"\n')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(checkout / '.venv')], check=True)
    (checkout / '.venv/.ee2kicad-ready').write_text(hashlib.sha256(project.read_bytes()).hexdigest())
    app = checkout / 'easyeda2kicad_local'
    app.mkdir()
    (app / '__init__.py').write_text('')
    (app / '__main__.py').write_text(
        'import json, os, sys\n'
        'print("EE_JSON=" + json.dumps({"cwd": os.environ["EE2KICAD_CWD"], "args": sys.argv[1:]}))\n'
        'sys.exit(7)\n')
    cmd = os.environ.get('COMSPEC', 'cmd.exe')
    original = subprocess.run([cmd, '/d', '/c', 'chcp'], capture_output=True, check=True)
    codepage = re.search(rb'(\d+)\s*$', original.stdout)[1].decode('ascii')
    harness = tmp_path / 'harness.bat'
    harness.write_text(
        '@echo off\nchcp 437 >nul\n'
        f'call "{checkout / "run.bat"}" "a&b" "link with spaces"\n'
        'set "ee_test_result=%errorlevel%"\nchcp\n'
        f'chcp {codepage} >nul\nexit /b %ee_test_result%\n')
    run = subprocess.run([cmd, '/d', '/c', str(harness)], cwd=tmp_path, capture_output=True)
    assert run.returncode == 7, run.stdout + run.stderr
    lines = run.stdout.decode('utf-8', errors='replace').splitlines()
    payload = json.loads(next(line.removeprefix('EE_JSON=') for line in lines if line.startswith('EE_JSON=')))
    assert payload == {'cwd': str(tmp_path), 'args': ['a&b', 'link with spaces']}
    assert re.search(rb'437\s*$', run.stdout)
    # The missing-Python branch must restore the code page too.
    (checkout / '.venv/Scripts/python.exe').rename(checkout / '.venv/Scripts/disabled-python.exe')
    env = dict(os.environ, PATH=str(Path(os.environ['SystemRoot']) / 'System32'))
    failed = subprocess.run([cmd, '/d', '/c', str(harness)], cwd=tmp_path, env=env, capture_output=True)
    assert failed.returncode == 1
    assert b'Python 3.11+' in failed.stderr and re.search(rb'437\s*$', failed.stdout)
