@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo PowerBot Launcher
echo.

REM ---- Check Python (py -3) ----
py -3 -c "import sys" >nul 2>nul
if errorlevel 1 goto :no_python

REM ---- Create .venv if missing ----
if exist ".venv\Scripts\python.exe" goto :venv_ok
echo Setting up PowerBot (first run)...
py -3 -m venv .venv >nul 2>nul
if errorlevel 1 goto :venv_fail

:venv_ok
REM ---- Activate .venv ----
call ".venv\Scripts\activate.bat" >nul 2>nul
if errorlevel 1 goto :venv_activate_fail

REM ---- Install dependencies (silent) ----
if not exist "requirements.txt" goto :missing_requirements
python -m pip install --upgrade pip --disable-pip-version-check >nul 2>nul
python -m pip install -r requirements.txt --disable-pip-version-check >nul 2>nul
if errorlevel 1 goto :deps_fail

REM ---- Verify .env ----
if not exist ".env" goto :missing_env

REM ---- Start bot ----
echo Starting PowerBot...
echo.
py bot.py
set "BOT_EXIT=%ERRORLEVEL%"
echo.
if "%BOT_EXIT%"=="0" (
  echo PowerBot closed normally.
) else (
  echo PowerBot stopped with exit code %BOT_EXIT%.
)
goto :pause_exit

:no_python
echo ERROR: Python 3 was not found.
echo.
echo Install Python 3, then run start.bat again.
echo.
echo Tip (Windows): You can install Python from the Microsoft Store.
goto :pause_exit

:missing_requirements
echo ERROR: requirements.txt not found.
goto :pause_exit

:venv_fail
echo ERROR: Failed to create the virtual environment (.venv).
goto :pause_exit

:venv_activate_fail
echo ERROR: Failed to activate .venv.
goto :pause_exit

:deps_fail
echo ERROR: Failed to install dependencies.
echo.
echo If this keeps failing, check your internet connection and antivirus, then try again.
goto :pause_exit

:missing_env
echo PowerBot setup required:
echo.
echo 1. Make a copy of .env.example
echo 2. Rename the copy to .env
echo 3. Open .env (it^'s a text file)
echo 4. Paste your bot token after DISCORD_TOKEN=
echo 5. Save the file
echo 6. Run start.bat again
goto :pause_exit

:pause_exit
echo.
pause
endlocal
