@echo off
setlocal enabledelayedexpansion
title L2 Geodata Converter

:: Resolve Python executable
set "PYTHON_EXE="
where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
) else (
    if exist "C:\Program Files\Python312\python.exe" (
        set "PYTHON_EXE=C:\Program Files\Python312\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) else if exist "C:\Python312\python.exe" (
        set "PYTHON_EXE=C:\Python312\python.exe"
    )
)

:: Select execution engine (Python or Compiled Standalone EXE)
set "RUN_CMD="
if not "%PYTHON_EXE%"=="" (
    set RUN_CMD="%PYTHON_EXE%" "%~dp0geotool.py"
) else if exist "%~dp0L2GeoConverter.exe" (
    set RUN_CMD="%~dp0L2GeoConverter.exe"
) else if exist "%~dp0dist\L2GeoConverter.exe" (
    set RUN_CMD="%~dp0dist\L2GeoConverter.exe"
) else (
    echo [ERROR] Neither Python 3.8+ nor L2GeoConverter.exe was found.
    echo Please install Python 3.8+ or download the compiled L2GeoConverter.exe release.
    pause
    exit /b 1
)

:: Case 1: CLI arguments or Drag and Drop
if not "%~1"=="" (
    if "%~2"=="" (
        if exist "%~f1" (
            set "EXT=%~x1"
            if /i "!EXT!"==".l2g" goto dragdrop
            if /i "!EXT!"==".l2j" goto dragdrop
            if /i "!EXT!"==".dat" goto dragdrop
        )
    )
    !RUN_CMD! %*
    exit /b %errorlevel%
)

:: Case 2: Launch Graphical User Interface (Default)
cd /d "%~dp0"
!RUN_CMD!
exit /b 0

:dragdrop
set "INPUT_FILE=%~f1"
set "FILE_DIR=%~dp1"
set "FILE_NAME=%~n1"
echo ========================================================
echo  L2 Geodata Converter - Quick Mode (Drag and Drop)
echo  File: !INPUT_FILE!
echo ========================================================
echo.
echo  [1] Diagnostics (Check NSWE, Cliffs, Squeezes)
echo  [2] Diagnose and Auto-Repair (--fix)
if /i "!EXT!"==".l2g" (
    echo  [3] Decrypt Lucera 2 .l2g to .l2j
    echo  [4] Convert Lucera 2 .l2g to PTS _conv.dat
)
if /i "!EXT!"==".l2j" (
    echo  [3] Encrypt .l2j to Lucera 2 .l2g
    echo  [4] Convert .l2j to PTS _conv.dat
)
if /i "!EXT!"==".dat" (
    echo  [3] Convert PTS _conv.dat to .l2j
    echo  [4] Convert PTS _conv.dat to Lucera 2 .l2g
)
echo.
set /p "DD_CHOICE=Select an option [1-4]: "

if "!DD_CHOICE!"=="1" (
    !RUN_CMD! diagnose "!INPUT_FILE!"
    pause
    exit /b 0
)
if "!DD_CHOICE!"=="2" (
    !RUN_CMD! diagnose "!INPUT_FILE!" --fix -o "!FILE_DIR!repaired"
    echo.
    echo Repaired file saved in: !FILE_DIR!repaired
    pause
    exit /b 0
)
if "!DD_CHOICE!"=="3" (
    if /i "!EXT!"==".l2g" (
        !RUN_CMD! l2g2l2j "!INPUT_FILE!" -o "!FILE_DIR!l2j" -y
        echo Converted to: !FILE_DIR!l2j
    )
    if /i "!EXT!"==".l2j" (
        !RUN_CMD! l2j2l2g "!INPUT_FILE!" -o "!FILE_DIR!l2g" -y
        echo Converted to: !FILE_DIR!l2g
    )
    if /i "!EXT!"==".dat" (
        !RUN_CMD! convert "!INPUT_FILE!" -o "!FILE_DIR!l2j" -y
        echo Converted to: !FILE_DIR!l2j
    )
    pause
    exit /b 0
)
if "!DD_CHOICE!"=="4" (
    if /i "!EXT!"==".l2g" (
        !RUN_CMD! l2g2pts "!INPUT_FILE!" -o "!FILE_DIR!pts" -y
        echo Converted to: !FILE_DIR!pts
    )
    if /i "!EXT!"==".l2j" (
        !RUN_CMD! l2j2pts "!INPUT_FILE!" -o "!FILE_DIR!pts" -y
        echo Converted to: !FILE_DIR!pts
    )
    if /i "!EXT!"==".dat" (
        !RUN_CMD! pts2l2g "!INPUT_FILE!" -o "!FILE_DIR!l2g" -y
        echo Converted to: !FILE_DIR!l2g
    )
    pause
    exit /b 0
)
exit /b 0
