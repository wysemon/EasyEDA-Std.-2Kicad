"""Command-line and interactive entry points shared by all launchers."""

import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .client import parse_uuid
from .workflow import run_items

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help='Convert public EasyEDA Standard components into local KiCad libraries.',
)


def version_callback(value):
    if value:
        typer.echo(f'easyeda2kicad-local {__version__}')
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool, typer.Option('--version', callback=version_callback, is_eager=True)
    ] = False,
):
    """Convert EasyEDA Standard components locally."""


def configure_console():
    # Windows redirected output can otherwise inherit a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def setup_logging(verbose):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format='%(message)s', force=True
    )
    # Never log HTTP headers, credentials, cookies or proxy configuration.
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)


def fail(message, *, verbose=False):
    typer.echo('Error: ' + str(message).replace('\n', ' ').replace('\r', ' '), err=True)
    if verbose:
        logging.getLogger(__name__).exception('Details')
    raise typer.Exit(1)


def caller_path(path):
    """Resolve user paths relative to the invoking directory, not the checkout."""
    if path.is_absolute():
        return path
    return (Path(os.environ.get('EE2KICAD_CWD') or Path.cwd()) / path).resolve()


def interactive_inputs():
    """Return fetch arguments; EOF and an empty line finish without a traceback."""
    try:
        if caller_path(Path('links.txt')).is_file():
            answer = input('Found links.txt, use it? [Y/n] ').strip().lower()
            if answer in ('', 'y', 'yes'):
                return ['--file', 'links.txt']
        values = []
        while True:
            try:
                value = input('Paste an EasyEDA component link (empty line to finish): ').strip()
            except EOFError:
                break
            if not value:
                break
            values.append(value)
        return values
    except (EOFError, KeyboardInterrupt):
        return []


def main(args=None):
    """Accept bare links, explicit subcommands, or no-argument interactive input."""
    configure_console()
    arguments = list(sys.argv[1:] if args is None else args)
    verbose = '--verbose' in arguments or '-v' in arguments
    try:
        if not arguments:
            arguments = interactive_inputs()
            if not arguments:
                typer.echo('No components supplied; nothing to do.')
                return
        if arguments[0] not in ('fetch', 'convert', '--help', '-h', '--version'):
            arguments.insert(0, 'fetch')
        program = Path(sys.argv[0]).stem
        app(args=arguments, prog_name='ee2kicad' if program == '__main__' else program)
    except Exception as e:
        if verbose:
            logging.getLogger(__name__).exception('Error')
        else:
            typer.echo(
                f'Error: {str(e).replace(chr(10), " ")}; check the input/output paths and retry (use --verbose for details).',
                err=True,
            )
        raise SystemExit(1) from None


@app.command()
def fetch(
    inputs: Annotated[
        list[str] | None, typer.Argument(help='Component URLs or 32-hex UUIDs.')
    ] = None,
    file: Annotated[
        Path | None, typer.Option('--file', help='One URL/UUID per line; # comments allowed.')
    ] = None,
    output: Annotated[Path, typer.Option('--output', '-o')] = Path('output'),
    force: Annotated[bool, typer.Option('--force')] = False,
    delay: Annotated[
        float,
        typer.Option(
            '--delay', min=1.0, help='At least 1 second between requests, plus 0–2s jitter.'
        ),
    ] = 4.0,
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    verbose: Annotated[bool, typer.Option('--verbose', '-v')] = False,
    validate: Annotated[
        bool,
        typer.Option('--validate', help='Require KiCad 8/9; validate copies before publishing.'),
    ] = False,
):
    """Fetch, cache and convert components sequentially."""
    configure_console()
    setup_logging(verbose)
    output = caller_path(output)
    file = caller_path(file) if file is not None else None
    values = list(inputs or [])
    if file:
        try:
            values.extend(
                line.strip()
                for line in file.read_text(encoding='utf-8-sig').splitlines()
                if line.strip() and not line.lstrip().startswith('#')
            )
        except (OSError, UnicodeError) as e:
            fail(
                f'Cannot read {file}: {e}; check the path and save the file as UTF-8.',
                verbose=verbose,
            )
    if not values:
        fail(
            'Supply a URL/UUID or --file links.txt, or run ee2kicad with no arguments for prompts.'
        )
    try:
        items = list(dict.fromkeys(parse_uuid(value) for value in values))
    except ValueError as e:
        fail(f'{e}; paste a public EasyEDA Standard component link or its UUID.', verbose=verbose)
    raise typer.Exit(
        run_items(
            items,
            output,
            force=force,
            delay=delay,
            dry_run=dry_run,
            validate=validate,
            verbose=verbose,
        )
    )


@app.command()
def convert(
    uuid: Annotated[str, typer.Argument(help='UUID already stored in output/*/raw.json.')],
    output: Annotated[Path, typer.Option('--output', '-o')] = Path('output'),
    dry_run: Annotated[bool, typer.Option('--dry-run')] = False,
    verbose: Annotated[bool, typer.Option('--verbose', '-v')] = False,
    validate: Annotated[
        bool,
        typer.Option('--validate', help='Require KiCad 8/9; validate copies before publishing.'),
    ] = False,
):
    """Re-convert cached data without any network requests."""
    configure_console()
    setup_logging(verbose)
    output = caller_path(output)
    try:
        uuid = parse_uuid(uuid)
    except ValueError as e:
        fail(f'{e}; use the UUID of a cached component.', verbose=verbose)
    raise typer.Exit(
        run_items(
            [uuid], output, cached_only=True, dry_run=dry_run, validate=validate, verbose=verbose
        )
    )
