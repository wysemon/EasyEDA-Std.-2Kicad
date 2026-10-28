import io
import sys

import pytest
from conftest import NEW, OLD
from rich.text import Text
from test_workflow import install_cache

from easyeda2kicad_local import cli


def invoke_main(monkeypatch, args, stdin='', *, program='euc2k'):
    monkeypatch.setattr(sys, 'stdin', io.StringIO(stdin))
    monkeypatch.setattr(sys, 'argv', [program, *args])
    try:
        cli.main()
    except SystemExit as e:
        return e.code
    return 0


def test_no_args_reads_multiple_links(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(cli, 'run_items', lambda items, root, **kwargs: calls.append(items) or 0)
    assert (
        invoke_main(monkeypatch, [], f'https://www.easyeda.com/component/{OLD}#x\n{NEW}\n\n') == 0
    )
    assert calls == [[OLD, NEW]]


@pytest.mark.parametrize('answer', ['', 'y', 'Y', 'yes'])
def test_default_links_file(monkeypatch, tmp_path, answer):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'links.txt').write_text('\ufeff' + NEW, encoding='utf-8')
    calls = []
    monkeypatch.setattr(cli, 'run_items', lambda items, root, **kwargs: calls.append(items) or 0)
    assert invoke_main(monkeypatch, [], answer + '\n') == 0
    assert calls == [[NEW]]


def test_declining_file_and_eof(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'links.txt').write_text('invalid')
    calls = []
    monkeypatch.setattr(cli, 'run_items', lambda items, root, **kwargs: calls.append(items) or 0)
    assert invoke_main(monkeypatch, [], 'n\n' + NEW) == 0
    assert calls == [[NEW]]


def test_empty_interactive_exits_without_fetch(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, 'run_items', lambda *a, **kw: pytest.fail('must not fetch'))
    assert invoke_main(monkeypatch, [], '\n') == 0
    assert 'nothing to do' in capsys.readouterr().out
    assert invoke_main(monkeypatch, [], '') == 0


@pytest.mark.parametrize(
    'args,cached', [([NEW], False), (['fetch', NEW], False), (['convert', NEW], True)]
)
def test_console_entrypoint_dispatch(monkeypatch, args, cached):
    calls = []
    monkeypatch.setattr(cli, 'run_items', lambda items, root, **kw: calls.append((items, kw)) or 0)
    assert invoke_main(monkeypatch, args) == 0
    assert calls[0][0] == [NEW]
    assert calls[0][1].get('cached_only', False) is cached
    if not cached:
        assert calls[0][1]['delay'] == 4.0


def test_console_command_declared():
    import tomllib
    from pathlib import Path

    config = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert config['project']['name'] == 'EasyEDA-Std.-2Kicad'
    assert config['project']['scripts'] == {
        'euc2k': 'easyeda2kicad_local.cli:main',
    }


@pytest.mark.parametrize(
    'program,expected',
    [
        ('euc2k', 'euc2k'),
        ('euc2k.exe', 'euc2k'),
        ('__main__.py', 'euc2k'),
    ],
)
def test_command_help_uses_command_name_and_module_default(monkeypatch, capsys, program, expected):
    assert invoke_main(monkeypatch, ['--help'], program=program) == 0
    assert f'Usage: {expected} ' in Text.from_ansi(capsys.readouterr().out).plain


def test_installed_console_command(tmp_path):
    import subprocess
    import sysconfig
    from pathlib import Path

    from easyeda2kicad_local import __version__

    executable = Path(sysconfig.get_path('scripts')) / (
        'euc2k.exe' if sys.platform == 'win32' else 'euc2k'
    )
    result = subprocess.run(
        [str(executable), '--version'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f'EasyEDA-Std.-2Kicad {__version__}'
    # Exercise no-argument prompts through the installed wrapper from another
    # directory, where no source checkout or default links.txt is available.
    interactive = subprocess.run(
        [str(executable)],
        cwd=tmp_path,
        input='\n',
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=30,
    )
    assert interactive.returncode == 0, interactive.stderr
    assert 'Paste an EasyEDA component link' in interactive.stdout


def test_friendly_bad_link(monkeypatch, capsys):
    assert invoke_main(monkeypatch, ['https://evil.test/component/' + NEW]) == 1
    error = capsys.readouterr().err
    assert len(error.splitlines()) == 1
    assert 'paste a public EasyEDA' in error and 'Traceback' not in error


@pytest.mark.parametrize('verbose', [False, True])
def test_friendly_network_failure(monkeypatch, tmp_path, capsys, verbose):
    import httpx

    def fail(self, *a, **kwargs):
        raise httpx.ConnectError('offline')

    monkeypatch.setattr('httpx.HTTPTransport.handle_request', fail)
    args = [NEW, '-o', str(tmp_path)] + (['--verbose'] if verbose else [])
    assert invoke_main(monkeypatch, args) == 1
    error = capsys.readouterr().err
    assert 'check your internet connection' in error
    assert ('Traceback' in error) is verbose
    if not verbose:
        assert len(error.splitlines()) == 1


def test_summary_and_absolute_library_paths(response, monkeypatch, tmp_path, capsys):
    output = tmp_path / 'output'
    output.mkdir()
    folder, _ = install_cache(output, response)
    uuid = response['result']['uuid']
    assert invoke_main(monkeypatch, ['convert', uuid, '-o', str(output)]) == 0
    text = capsys.readouterr().out
    assert '1 succeeded, 0 failed, 0 skipped' in text
    assert f'Output: {output.resolve()}' in text
    assert f'add {next(folder.glob("*.kicad_sym")).resolve()} in Symbol Libraries' in text
    assert f'add {next(folder.glob("*.pretty")).resolve()} in Footprint Libraries' in text
    assert invoke_main(monkeypatch, [uuid, '-o', str(output)]) == 0
    assert '0 succeeded, 0 failed, 1 skipped' in capsys.readouterr().out


def test_403_stops_run_with_friendly_fix(monkeypatch, tmp_path, capsys):
    from test_client import make_client

    client, clock, calls = make_client([403, 429])
    monkeypatch.setattr('easyeda2kicad_local.workflow.EasyEDAClient', lambda delay: client)
    assert invoke_main(monkeypatch, [NEW, OLD, '-o', str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert 'Wait before retrying' in captured.err
    assert 'Traceback' not in captured.err
    assert '0 succeeded, 1 failed, 0 skipped' in captured.out
    assert 'Not processed: 1' in captured.out
    assert len(calls) == 2 and clock.sleeps == [0.0, 30.0]


def test_unicode_output_with_legacy_console_encoding(response, tmp_path):
    import json
    import os
    import subprocess

    output = tmp_path / '输出'
    output.mkdir()
    folder, _ = install_cache(output, response)
    response['result']['title'] = '你好 électricité'
    response['result']['owner']['nickname'] = '作者'
    (folder / 'raw.json').write_text(json.dumps(response, ensure_ascii=False), encoding='utf-8')
    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'easyeda2kicad_local',
            'convert',
            response['result']['uuid'],
            '-o',
            str(output),
        ],
        env=dict(os.environ, PYTHONIOENCODING='ascii', PYTHONUTF8='0'),
        capture_output=True,
        encoding='utf-8',
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '输出' in result.stdout and '1 succeeded' in result.stdout
    assert '作者' in (folder / 'CREDITS.txt').read_text(encoding='utf-8')


def test_version_entrypoint(monkeypatch, capsys):
    from easyeda2kicad_local import __version__

    assert invoke_main(monkeypatch, ['--version']) == 0
    assert capsys.readouterr().out.strip() == f'EasyEDA-Std.-2Kicad {__version__}'


def test_version_matches_project_and_installed_metadata():
    import tomllib
    from importlib.metadata import version
    from pathlib import Path

    from easyeda2kicad_local import __version__

    project = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert project['project']['version'] == __version__ == version('EasyEDA-Std.-2Kicad')
