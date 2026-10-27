@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
pushd "%~dp0" || exit /b 1

if exist ".venv\Scripts\python.exe" goto check_venv
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto create_py
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto create_python
echo Python 3.11+ is required; install it from https://www.python.org/downloads/ and enable PATH, then try again. 1>&2
goto failed

:create_py
py -3 -m venv ".venv"
if errorlevel 1 goto venv_failed
goto check_venv

:create_python
python -m venv ".venv"
if errorlevel 1 goto venv_failed

:check_venv
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto old_venv
if exist ".venv\.ee2kicad-ready" goto run
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto install_failed
type nul > ".venv\.ee2kicad-ready"
if errorlevel 1 goto failed

:run
".venv\Scripts\python.exe" -m easyeda2kicad_local %*
set "ee_exit=%errorlevel%"
popd
exit /b %ee_exit%

:old_venv
echo The existing .venv needs Python 3.11+; rename .venv, install Python from https://www.python.org/downloads/ and retry. 1>&2
goto failed
:venv_failed
echo Could not create .venv; check your Python installation and folder permissions, then retry. 1>&2
goto failed
:install_failed
echo Setup failed; check your internet connection and Python/pip installation, then run this command again. 1>&2
:failed
popd
exit /b 1
