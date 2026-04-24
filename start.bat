@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   === WeChat Diary ===
echo.

call :detect_python
if not "%errorlevel%"=="0" exit /b %errorlevel%

set "ATTEMPT=0"
set "MAX_ATTEMPTS=3"
set "APP_EXIT=0"

:main_loop
set /a ATTEMPT+=1

call :ensure_login
set "LOGIN_EXIT=%errorlevel%"
if not "%LOGIN_EXIT%"=="0" (
    echo.
    echo   Login failed or cancelled ^(exit=%LOGIN_EXIT%^)
    goto :end
)

call :run_main
set "APP_EXIT=!errorlevel!"

if "%APP_EXIT%"=="2" (
    if !ATTEMPT! LSS %MAX_ATTEMPTS% (
        echo.
        echo   Session expired - re-login attempt !ATTEMPT!/%MAX_ATTEMPTS%
        echo.
        goto :force_relogin
    ) else (
        echo.
        echo   Session expired - max attempts reached ^(%MAX_ATTEMPTS%^)
        echo   Please try again later.
    )
)
goto :end

:force_relogin
del /q ilink_state.json 2>nul
goto :main_loop

:end
echo.
echo   ============================================
if "%APP_EXIT%"=="0" (
    echo   Exited normally.
) else (
    echo   Exited with code %APP_EXIT%.
)
echo   ============================================
pause
exit /b %APP_EXIT%

:detect_python
set "PY_CMD="
call :try_python "py"
if defined PY_CMD goto :python_ready
call :try_python "python"
if defined PY_CMD goto :python_ready

if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" (
    call :try_python "%LocalAppData%\Programs\Python\Launcher\py.exe"
    if defined PY_CMD goto :python_ready
)

for /f "delims=" %%P in ('dir /b /ad /o-n "%LocalAppData%\Programs\Python\Python*" 2^>nul') do (
    if exist "%LocalAppData%\Programs\Python\%%P\python.exe" (
        call :try_python "%LocalAppData%\Programs\Python\%%P\python.exe"
        if defined PY_CMD goto :python_ready
    )
)

for /f "delims=" %%P in ('dir /b /ad /o-n "%ProgramFiles%\Python*" 2^>nul') do (
    if exist "%ProgramFiles%\%%P\python.exe" (
        call :try_python "%ProgramFiles%\%%P\python.exe"
        if defined PY_CMD goto :python_ready
    )
)

if not defined PY_CMD (
    echo   Python not found.
    echo   Install Python 3.11+ and make sure py.exe or python.exe is available in PATH.
    pause
    exit /b 1
)
:python_ready
exit /b 0

:try_python
set "CANDIDATE=%~1"
"%CANDIDATE%" --version >nul 2>nul
if not errorlevel 1 set "PY_CMD=%CANDIDATE%"
exit /b 0

:ensure_login
if not exist ilink_state.json goto :login

cd src
%PY_CMD% ilink.py status
set "STATUS_EXIT=%errorlevel%"
cd ..
if "%STATUS_EXIT%"=="0" exit /b 0

echo.
echo   Local session invalid - re-login required
echo.
goto :login

:login
echo   Scan QR code to login...
echo.
cd src
%PY_CMD% ilink.py login
set "LOGIN_EXIT=%errorlevel%"
cd ..
if not "%LOGIN_EXIT%"=="0" exit /b %LOGIN_EXIT%
echo.
exit /b 0

:run_main
echo   Starting main...
echo.
cd src
%PY_CMD% main.py
set "MAIN_EXIT=%errorlevel%"
cd ..
exit /b %MAIN_EXIT%
