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

conda run -n pgl python scripts\designer.py
if errorlevel 1 (
    echo.
    echo [ERROR] The Plant Designer failed. This may be because the "pgl" conda environment does not exist.
    echo   Create it with:
    echo     conda create -n pgl python=3.10 openalea.plantgl -c openalea3 -c conda-forge -y
    echo     conda run -n pgl pip install trimesh numpy
    echo.
    echo   If the env exists and the error persists, see the traceback above.
    pause
)
