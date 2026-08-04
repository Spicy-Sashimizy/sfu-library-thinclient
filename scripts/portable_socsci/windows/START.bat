@echo off
REM ===================================================================
REM  SFU Library (portable social-sciences edition) — double-click launcher
REM
REM  Ships at the BUNDLE ROOT of the thumb drive. USB AutoRun is dead on
REM  modern Windows (design doc §7/§8), so the user double-clicks this file.
REM  It runs entirely from the drive; nothing is installed.
REM
REM  Layout it expects (assembled by phase 5, scripts/portable_socsci/):
REM    <root>\START.bat                       (this file)
REM    <root>\regen_seismic_manifest.py
REM    <root>\python\python.exe               (relocatable CPython, CPU wheels,
REM                                            seismic.pyd on the import path)
REM    <root>\src\sfu_library_mcp_http.py     (+ src\lib\...)
REM    <root>\web\...                         (the /app GUI)
REM    <root>\thinclient_index\...            (meta.sqlite, sections\, manifest)
REM    <root>\seismic\shards.e5.v2.json       (+ 8 *.e5.v2.mmap shard dirs)
REM    <root>\models\splade_onnx_fused\...    (SPLADE query encoder)
REM ===================================================================
setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PY=%ROOT%\python\python.exe"
if not exist "%PY%" (
  echo [START] bundled python not found at "%PY%".
  echo         This bundle's Windows runtime layer has not been assembled yet
  echo         ^(phase 5^). See docs\PORTABLE_SOCSCI_WINDOWS_BUNDLE.md.
  pause
  exit /b 1
)

REM --- 1. Repoint the seismic manifest at wherever this drive is mounted now.
echo [START] locating seismic shards on this drive...
"%PY%" "%ROOT%\regen_seismic_manifest.py" "%ROOT%" || (
  echo [START] failed to repoint the seismic manifest & pause & exit /b 1
)

REM --- 2. Bundle serving env (all paths on the drive; dense stripped, D1).
set "SFU_SEARCH_BACKEND=thinclient"
set "SFU_SPLADE_BACKEND=seismic"
set "SFU_THINCLIENT_INDEX_ROOT=%ROOT%\thinclient_index"
set "SFU_SEISMIC_SHARD_MANIFEST=%ROOT%\seismic\shards.e5.v2.json"
set "SFU_SPLADE_MODEL_PATH=%ROOT%\models\splade_onnx_fused"
set "SFU_SEISMIC_LOAD_MODE=mmap"
REM Data is already local on the drive — no staging copy.
set "SFU_SEISMIC_STAGE_DIR="
REM Dense leg is stripped from this bundle; keep its warm cache off.
set "SFU_DENSE_WARMCACHE=0"
REM Bind to loopback only — this is a single-user desktop app, not a server.
set "MCP_HTTP_HOST=127.0.0.1"
if "%MCP_HTTP_PORT%"=="" set "MCP_HTTP_PORT=8080"

REM --- 3. Launch the server (from src\, like serve_http.sh does).
echo [START] launching SFU Library on http://127.0.0.1:%MCP_HTTP_PORT%/app ...
pushd "%ROOT%\src"
start "SFU Library (server)" /min "%PY%" sfu_library_mcp_http.py
popd

REM --- 4. Wait for /health to report warm (WI-6: "up" != "warm"), then open UI.
echo [START] waiting for the index to warm up (first load mmaps ~42 GiB)...
powershell -NoProfile -Command ^
  "$u='http://127.0.0.1:%MCP_HTTP_PORT%/health';" ^
  "for($i=0;$i -lt 180;$i++){" ^
  "  try{$r=Invoke-RestMethod -Uri $u -TimeoutSec 2;" ^
  "      if($r.status -eq 'warm' -or $r.status -eq 'ok'){exit 0}}catch{}" ^
  "  Start-Sleep -Seconds 1}" ^
  "exit 1"
if errorlevel 1 (
  echo [START] server did not report healthy in time; opening the UI anyway.
)

start "" "http://127.0.0.1:%MCP_HTTP_PORT%/app"
echo [START] UI opened. Close this window to stop the server.
echo         ^(the server runs in the minimized "SFU Library (server)" window^)
pause
endlocal
