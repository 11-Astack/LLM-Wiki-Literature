@echo off
setlocal DisableDelayedExpansion
set "PROTOTYPE_ROOT=%~dp0"
if not exist "%PROTOTYPE_ROOT%runtime\python\python.exe" goto missing_python
if not exist "%PROTOTYPE_ROOT%launch.py" goto missing_entry
"%PROTOTYPE_ROOT%runtime\python\python.exe" -X utf8 -I -B -S "%PROTOTYPE_ROOT%launch.py" %*
set "PROTOTYPE_EXIT=%ERRORLEVEL%"
if not "%PROTOTYPE_EXIT%"=="0" echo [START_FAILED] Exit code: %PROTOTYPE_EXIT%
exit /b %PROTOTYPE_EXIT%

:missing_python
echo [E10] Bundled Python is missing: "%PROTOTYPE_ROOT%runtime\python\python.exe"
if exist "%PROTOTYPE_ROOT%REQUIREMENTS.md" type "%PROTOTYPE_ROOT%REQUIREMENTS.md"
exit /b 10

:missing_entry
echo [E11] Fixed entry point is missing: "%PROTOTYPE_ROOT%launch.py"
if exist "%PROTOTYPE_ROOT%REQUIREMENTS.md" type "%PROTOTYPE_ROOT%REQUIREMENTS.md"
exit /b 11
