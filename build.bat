@echo off
REM Windows build script for ProcessAudioTap

echo 🔨 ProcessAudioTap Build Script (Windows)
echo ==========================================

setlocal EnableDelayedExpansion

REM Colors for Windows (limited support)
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "NC=[0m"

REM Default options
set CLEAN=false
set BUILD=true
set TEST=false
set INSTALL=false
set DEV=false
set COVERAGE=false

REM Parse arguments
:parse
if "%~1"=="" goto :start
if /i "%~1"=="--clean" set CLEAN=true
if /i "%~1"=="--test" set TEST=true
if /i "%~1"=="--install" set INSTALL=true
if /i "%~1"=="--dev" set DEV=true && set BUILD=false
if /i "%~1"=="--coverage" set TEST=true && set COVERAGE=true
if /i "%~1"=="--all" set CLEAN=true && set BUILD=true && set TEST=true
if /i "%~1"=="--help" goto :help
shift
goto :parse

:help
echo Usage: %0 [options]
echo Options:
echo   --clean      Clean build artifacts
echo   --test       Run tests
echo   --install    Install built package
echo   --dev        Set up development environment
echo   --coverage   Run tests with coverage
echo   --all        Clean, build, and test
echo   --help       Show this help
exit /b 0

:start

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%NC% Python is not installed or not in PATH
    exit /b 1
)

REM Get Python version
for /f "tokens=2" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo %BLUE%[BUILD]%NC% Using Python %PYTHON_VERSION%

REM Check for Visual Studio Build Tools
cl.exe >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%NC% Visual Studio Build Tools not found
    echo Please install Visual Studio Build Tools with MSVC compiler
    echo Download from: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
    exit /b 1
)
echo %GREEN%[SUCCESS]%NC% Visual Studio Build Tools found

REM Clean if requested
if "%CLEAN%"=="true" (
    echo %BLUE%[BUILD]%NC% Cleaning build artifacts...
    if exist build\ rmdir /s /q build\
    if exist dist\ rmdir /s /q dist\
    if exist *.egg-info\ rmdir /s /q *.egg-info\
    for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
    del /s /q *.pyc >nul 2>&1
    del /s /q *.pyo >nul 2>&1
    if exist .mypy_cache\ rmdir /s /q .mypy_cache\
    if exist .pytest_cache\ rmdir /s /q .pytest_cache\
    if exist .coverage del .coverage
    if exist htmlcov\ rmdir /s /q htmlcov\
    echo %GREEN%[SUCCESS]%NC% Cleaned build artifacts
)

REM Set up development environment
if "%DEV%"=="true" (
    echo %BLUE%[BUILD]%NC% Setting up development environment...
    
    python -m pip install --upgrade pip
    python -m pip install build wheel
    python -m pip install -e .[dev,contrib]
    
    REM Create virtual environment if it doesn't exist
    if not exist venv\ (
        echo %BLUE%[BUILD]%NC% Creating virtual environment...
        python -m venv venv
        echo %GREEN%[SUCCESS]%NC% Created virtual environment in .\venv
        echo Activate with: venv\Scripts\activate
    )
    
    echo %GREEN%[SUCCESS]%NC% Development environment ready
    exit /b 0
)

REM Build package
if "%BUILD%"=="true" (
    echo %BLUE%[BUILD]%NC% Installing dependencies...
    python -m pip install --upgrade pip build wheel
    
    REM Install project dependencies
    python -m pip install -e .
    
    echo %BLUE%[BUILD]%NC% Building package...
    python -m build
    
    echo %GREEN%[SUCCESS]%NC% Package built successfully
)

REM Run tests
if "%TEST%"=="true" (
    echo %BLUE%[BUILD]%NC% Running tests...
    
    if "%COVERAGE%"=="true" (
        python -m pytest --cov=proctap --cov-report=html --cov-report=term
        echo %GREEN%[SUCCESS]%NC% Tests completed with coverage report in htmlcov/
    ) else (
        python -m pytest -v
        echo %GREEN%[SUCCESS]%NC% Tests completed
    )
)

REM Install package
if "%INSTALL%"=="true" (
    echo %BLUE%[BUILD]%NC% Installing package...
    
    REM Find the latest wheel
    for /f "delims=" %%f in ('dir /b /o:d dist\*.whl 2^>nul') do set WHEEL=%%f
    
    if not defined WHEEL (
        echo %RED%[ERROR]%NC% No wheel found. Run build first.
        exit /b 1
    )
    
    python -m pip install --force-reinstall "dist\%WHEEL%"
    echo %GREEN%[SUCCESS]%NC% Installed: %WHEEL%
)

echo %GREEN%[SUCCESS]%NC% Build script completed successfully!