@echo off
REM ===================================================================
REM  Duck Library (portable social-sciences edition) - SETUP
REM
REM  Double-click this to run the install wizard. It lets you:
REM    * Install to this PC (fastest), OR
REM    * Hybrid (fast parts on PC, seismic streamed from USB), OR
REM    * Run from USB (nothing installed; sequential search queue),
REM  and can free space by moving your large files to the USB first
REM  (verified copy, then delete; MOVE-BACK.bat restores them).
REM
REM  A .ps1 cannot be double-clicked to run, so this .bat launches it
REM  with an execution-policy bypass scoped to this one process only.
REM ===================================================================
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%HERE%install_wizard.ps1"
if errorlevel 1 (
  echo.
  echo Setup exited with an error. See any message above.
  pause
)
endlocal
