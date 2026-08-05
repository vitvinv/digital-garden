@echo off
rem Plant Designer launcher — uses the "pgl" conda environment.
rem Double-click this file from anywhere, or run:  designer.bat

cd /d "%~dp0"

where conda >nul 2>nul
if errorlevel 1 (
    echo [ERROR] conda not found on PATH.
    echo   Install Miniconda from https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe
    echo   and make sure "Add conda to PATH" is checked, then reopen this window.
    pause
    exit /b 1
)

call conda activate pgl 2>nul
if errorlevel 1 (
    echo [ERROR] conda environment "pgl" not found.
    echo   Create it with:
    echo     conda create -n pgl python=3.10 openalea.plantgl -c openalea3 -c conda-forge -y
    echo     conda activate pgl
    echo     pip install trimesh numpy
    pause
    exit /b 1
)

python scripts\designer.py
if errorlevel 1 (
    echo.
    echo [ERROR] Plant Designer exited with an error. See the traceback above.
    pause
)
