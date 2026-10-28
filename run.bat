@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "EUC2K_CWD=%CD%"
set "euc2k_exit=1"
set "euc2k_pushed="
set "euc2k_codepage="
for /f "tokens=2 delims=:" %%C in ('chcp') do for /f "tokens=*" %%D in ("%%C") do set "euc2k_codepage=%%D"
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto finish
set "euc2k_pushed=1"

if exist ".venv\Scripts\python.exe" goto check_venv
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto create_py
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto create_python
echo euc2k.py: Python 3.11+ is required; install it from https://www.python.org/downloads/ and enable PATH, then try again. 1>&2
goto finish

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
".venv\Scripts\python.exe" "%~dp0scripts\bootstrap.py"
if errorlevel 1 goto finish

".venv\Scripts\python.exe" -m euc2k %*
set "euc2k_exit=%errorlevel%"
goto finish

:old_venv
echo The existing .venv needs Python 3.11+; rename .venv, install Python from https://www.python.org/downloads/ and retry. 1>&2
goto finish
:venv_failed
echo Could not create .venv; check your Python installation and folder permissions, then retry. 1>&2
:finish
if defined euc2k_pushed popd
if defined euc2k_codepage chcp %euc2k_codepage% >nul
exit /b %euc2k_exit%
