"""Invalid batch entries must not prevent independent valid inputs from running."""

import pytest
from conftest import FIXTURES, NEW, OLD
from test_client import make_client
from test_entrypoint import invoke_main
from typer.testing import CliRunner

from euc2k import cli
from euc2k.client import EasyEDAClient


@pytest.mark.parametrize('status', [0, 1])
def test_mixed_arguments_keep_valid_order_deduplicate_and_forward_options(
    monkeypatch, tmp_path, status
):
    calls = []

    def run(items, root, **options):
        calls.append((items, root, options))
        return status

    monkeypatch.setattr(cli, 'run_items', run)
    invalid = ['not-a-uuid', f'https://other.test/component/{NEW}']
    result = CliRunner().invoke(
        cli.app,
        [
            'fetch',
            invalid[0],
            NEW.upper(),
            invalid[1],
            OLD,
            f'https://www.easyeda.com/component/{NEW}/?x=1#fragment',
            '--output',
            str(tmp_path),
            '--force',
            '--delay',
            '1.5',
            '--dry-run',
            '--verbose',
            '--validate',
        ],
    )
    assert result.exit_code == 1
    assert calls == [
        (
            [NEW, OLD],
            tmp_path,
            dict(force=True, delay=1.5, dry_run=True, verbose=True, validate=True),
        )
    ]
    assert all(f'Invalid input {value!r}' in result.output for value in invalid)


@pytest.mark.parametrize('status', [0, 1])
def test_valid_batch_retains_workflow_exit_status(monkeypatch, status):
    calls = []
    monkeypatch.setattr(cli, 'run_items', lambda items, *a, **kw: calls.append(items) or status)
    result = CliRunner().invoke(cli.app, ['fetch', OLD, NEW, OLD.upper()])
    assert result.exit_code == status
    assert calls == [[OLD, NEW]]


def test_arguments_then_file_preserve_order_and_report_original_line_numbers(monkeypatch, tmp_path):
    links = tmp_path / 'links with spaces.txt'
    links.write_text(
        f'\ufeff# comment\n\n{OLD}\nbad-file-entry\n {NEW.upper()} \n# another comment\n'
        f'https://[broken\n{"0" * 32}\n',
        encoding='utf-8',
    )
    calls = []
    monkeypatch.setattr(cli, 'run_items', lambda items, *a, **kw: calls.append(items) or 0)
    result = CliRunner().invoke(cli.app, ['fetch', NEW, 'bad-argument', '--file', str(links)])
    assert result.exit_code == 1
    assert calls == [[NEW, OLD, '0' * 32]]
    assert f'{links}:4: Invalid input' in result.output
    assert f'{links}:7: Invalid input' in result.output
    assert all(
        value in result.output for value in ('bad-argument', 'bad-file-entry', 'https://[broken')
    )
    assert result.output.count('Invalid input') == 3
    assert 'Traceback' not in result.output


@pytest.mark.parametrize('source', ['arguments', 'file', 'interactive'])
def test_all_invalid_inputs_never_enter_workflow_or_make_requests(
    monkeypatch, tmp_path, capsys, source
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, 'run_items', lambda *a, **kw: pytest.fail('No valid input to process'))
    monkeypatch.setattr(EasyEDAClient, 'component', lambda *a: pytest.fail('No requests allowed'))
    if source == 'file':
        links = tmp_path / 'invalid.txt'
        links.write_text('# comment\nbad-one\n\nbad-two\n', encoding='utf-8')
        args, stdin = ['fetch', '--file', str(links)], ''
    elif source == 'interactive':
        args, stdin = [], 'bad-one\nbad-two\n\n'
    else:
        args, stdin = ['bad-one', 'bad-two'], ''
    assert invoke_main(monkeypatch, args, stdin) == 1
    errors = capsys.readouterr().err
    assert 'bad-one' in errors and 'bad-two' in errors
    assert errors.count('Invalid input') == 2
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('default_file', [False, True])
def test_interactive_input_processes_valid_entries_despite_invalid_ones(
    monkeypatch, tmp_path, capsys, default_file
):
    monkeypatch.chdir(tmp_path)
    contents = f'bad-one\n{NEW.upper()}\n{OLD}\nbad-two\n{NEW}\n'
    if default_file:
        (tmp_path / 'links.txt').write_text(contents, encoding='utf-8')
    calls = []
    monkeypatch.setattr(cli, 'run_items', lambda items, *a, **kw: calls.append(items) or 0)
    assert invoke_main(monkeypatch, [], '\n' if default_file else contents + '\n') == 1
    assert calls == [[NEW, OLD]]
    errors = capsys.readouterr().err
    assert 'bad-one' in errors and 'bad-two' in errors
    if default_file:
        assert 'links.txt:1:' in errors and 'links.txt:4:' in errors


def test_mixed_batch_really_converts_valid_components(monkeypatch, tmp_path, capsys):
    calls = []

    def component(self, uuid):
        calls.append(uuid)
        return (FIXTURES / f'{uuid}.json').read_bytes()

    monkeypatch.setattr(EasyEDAClient, 'component', component)
    assert invoke_main(monkeypatch, [NEW, 'invalid', OLD, NEW, '-o', str(tmp_path)]) == 1
    assert calls == [NEW, OLD]
    captured = capsys.readouterr()
    assert '2 succeeded, 0 failed' in captured.out
    assert "Invalid input 'invalid'" in captured.err
    assert len(list(tmp_path.glob('*/*.kicad_sym'))) == 2


def test_invalid_inputs_do_not_reset_or_bypass_access_denial_stop(monkeypatch, tmp_path, capsys):
    client, clock, calls = make_client([403, 429])
    monkeypatch.setattr('euc2k.workflow.EasyEDAClient', lambda delay: client)
    assert invoke_main(monkeypatch, ['bad-one', NEW, 'bad-two', OLD, '-o', str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert 'bad-one' in captured.err and 'bad-two' in captured.err
    assert 'Two consecutive 429/403 responses' in captured.err
    assert 'Not processed: 1' in captured.out
    assert len(calls) == 2 and clock.sleeps == [0.0, 30.0]
