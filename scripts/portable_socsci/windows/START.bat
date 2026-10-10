@echo off
REM ===================================================================
REM  Duck Library (portable social-sciences edition) - launcher
REM
REM  Double-clicked directly on the USB  -> portable mode (everything on
REM  the drive; sequential search queue ON). Or written + launched by the
REM  setup wizard (SETUP.bat) with an sfu_runtime.cfg next to it that
REM  selects Install-to-PC / Hybrid / Run-from-USB.
REM
REM  sfu_runtime.cfg (KEY=VALUE, written by install_wizard.ps1):
REM    MODE=pc|hybrid|usb
REM    SEQUENTIAL=0|1                 (1 = one-at-a-time search queue on)
REM    INDEX_ROOT=<...>\thinclient_index
REM    MODEL_ROOT=<...>\models
REM    SEISMIC_BUNDLE_ROOT=<root that contains seismic\>   (USB in Hybrid)
REM
REM  START.bat always sits WITH the runtime it launches (the wizard copies
REM  it alongside python\/src\/thinclient_index\ for pc/hybrid), so %ROOT%
REM  locates python + index; only seismic's location varies by mode.
REM ===================================================================
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM --- Defaults = portable mode (no wizard; user double-clicked on USB) ---
set "MODE=usb"
set "SEQUENTIAL=1"
set "INDEX_ROOT=%ROOT%\thinclient_index"
set "MODEL_ROOT=%ROOT%\models"
set "SEISMIC_BUNDLE_ROOT=%ROOT%"

REM --- Wizard config overrides, if present next to this launcher ---
if exist "%ROOT%\sfu_runtime.cfg" (
  echo [START] reading sfu_runtime.cfg ...
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%\sfu_runtime.cfg") do (
    set "%%A=%%B"
  )
)

set "PY=%ROOT%\python\python.exe"
if not exist "%PY%" (
  echo [START] bundled python not found at "%PY%".
  echo         The Windows runtime has not been built yet - run
  echo         build_windows_runtime.ps1 once on a Windows PC with Rust.
  echo         See docs\PORTABLE_SOCSCI_WINDOWS_BUNDLE.md.
  pause
  exit /b 1
)

REM --- 1. Repoint the seismic manifest at wherever seismic lives right now.
REM     (Hybrid: SEISMIC_BUNDLE_ROOT is the USB; pc/usb: same as ROOT.)
echo [START] locating seismic shards under "%SEISMIC_BUNDLE_ROOT%\seismic" ...
"%PY%" "%ROOT%\regen_seismic_manifest.py" "%SEISMIC_BUNDLE_ROOT%" || (
  echo [START] failed to repoint the seismic manifest & pause & exit /b 1
)

REM --- 2. Serving env (paths resolved from the mode above; dense stripped, D1).
set "SFU_SEARCH_BACKEND=thinclient"
set "SFU_SPLADE_BACKEND=seismic"
set "SFU_THINCLIENT_INDEX_ROOT=%INDEX_ROOT%"
set "SFU_SEISMIC_SHARD_MANIFEST=%SEISMIC_BUNDLE_ROOT%\seismic\shards.e5.v2.json"
set "SFU_SPLADE_MODEL_PATH=%MODEL_ROOT%\splade_onnx_fused"
set "SFU_SEISMIC_LOAD_MODE=mmap"
set "SFU_SEISMIC_STAGE_DIR="
set "SFU_DENSE_WARMCACHE=0"
REM Sequential mode: the server advertises this on /health so the web UI turns
REM the one-at-a-time search queue ON by default (user-toggleable in Settings).
set "SFU_SEQUENTIAL_MODE=%SEQUENTIAL%"
REM Bind to loopback only - this is a single-user desktop app, not a server.
set "MCP_HTTP_HOST=127.0.0.1"
if "%MCP_HTTP_PORT%"=="" set "MCP_HTTP_PORT=8080"

echo [START] mode=%MODE%  sequential=%SEQUENTIAL%

REM --- 3. Launch the server (from src\, like serve_http.sh does).
echo [START] launching Duck Library on http://127.0.0.1:%MCP_HTTP_PORT%/app ...
pushd "%ROOT%\src"
start "Duck Library (server)" /min "%PY%" sfu_library_mcp_http.py
popd

REM --- 4. Wait for /health to report warm (WI-6: "up" != "warm"), then open UI.
echo [START] waiting for the index to warm up (first load mmaps the shards)...
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
echo         (the server runs in the minimized "Duck Library (server)" window)
pause
endlocal
