@echo off
setlocal enabledelayedexpansion
title Karen Voice Assistant
cd /d "%~dp0"

echo ===================================================
echo             Karen Voice Assistant
echo ===================================================
echo.

:: ── 1. Ensure Ollama server is running ──────────────────────
echo [1/3] Checking Ollama service...
curl -s -o nul -w "" http://localhost:11434/ >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo Ollama server is already running.
    goto ollama_ready
)

echo Ollama server is not running. Starting it now...
start "Ollama Server" ollama serve

echo Waiting for Ollama server to be ready...
set RETRIES=0

:wait_ollama
timeout /t 1 /nobreak >nul
curl -s -o nul -w "" http://localhost:11434/ >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo Ollama server is ready!
    goto ollama_ready
)
set /a RETRIES+=1
if !RETRIES! LSS 15 (
    echo   Still waiting... ^(!RETRIES!/15^)
    goto wait_ollama
)

echo.
echo ERROR: Ollama server did not start within 15 seconds.
echo Please make sure Ollama is installed: https://ollama.com
pause
exit /b 1

:ollama_ready

:: ── 2. Ensure llama3 model is available ─────────────────────
echo [2/3] Checking llama3 model...
ollama list 2>&1 | findstr /i "llama3" >nul
if !ERRORLEVEL! NEQ 0 (
    echo Model 'llama3' not found. Pulling llama3 now ^(this may take a few minutes^)...
    ollama pull llama3
) else (
    echo Model 'llama3' is ready.
)

:: ── 3. Launch Karen ─────────────────────────────────────────
echo.
echo [3/3] Starting Karen...
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at .venv\
    echo Run: python -m venv .venv
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python voice_assistant.py
pause
