@echo off
REM 网页版入口: 双击后浏览器自动打开本地页面, 扫码/选文件夹/启停都在页面里做。
REM (命令行版入口是 start.bat, 两者等价, 用哪个都行)
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo   === WeChat Diary - Web UI ===
echo.

call :detect_python
if not "%errorlevel%"=="0" exit /b %errorlevel%

cd src
%PY_CMD% webui.py
set "APP_EXIT=%errorlevel%"
cd ..

echo.
if not "%APP_EXIT%"=="0" (
    echo   Exited with code %APP_EXIT%.
    echo   Check the messages above, or data\logs\ for details.
)
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
