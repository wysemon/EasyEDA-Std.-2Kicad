"""Optional KiCad validation that never upgrades the user's generated originals."""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def validate_libraries(folder: Path, name: str):
    executable = shutil.which('kicad-cli')
    if executable is None:
        print('Validation unavailable: install KiCad 8/9 and add kicad-cli to PATH, then retry --validate.')
        return False
    passed = True
    with tempfile.TemporaryDirectory(prefix='ee2kicad-validate-') as temporary:
        work = Path(temporary)
        symbol = work / f'{name}.kicad_sym'
        pretty = work / f'{name}.pretty'
        shutil.copy2(folder / symbol.name, symbol)
        shutil.copytree(folder / pretty.name, pretty)
        # Keep KiCad's settings/cache writes temporary as well as its upgrades.
        env = dict(os.environ)
        for key in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
            location = work / key.lower()
            location.mkdir()
            env[key] = str(location)
        env['KICAD_CONFIG_HOME'] = str(work / 'kicad-config')
        for kind, path in [('sym', symbol), ('fp', pretty)]:
            try:
                result = subprocess.run([executable, kind, 'upgrade', '--force', str(path)],
                                        env=env, capture_output=True, text=True,
                                        encoding='utf-8', errors='replace', timeout=60)
                ok = result.returncode == 0
                log.debug('KiCad %s validation output: %s %s', kind, result.stdout, result.stderr)
            except (OSError, subprocess.TimeoutExpired):
                ok = False
                log.debug('KiCad validation could not run', exc_info=True)
            print(f'Validation {kind}: {"PASS" if ok else "FAIL"} ({name})')
            if not ok:
                log.error('KiCad %s validation failed; check the generated library in KiCad or rerun with --verbose.', kind)
            passed &= ok
    return passed
