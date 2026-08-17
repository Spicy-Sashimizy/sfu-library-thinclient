@echo off
REM ===================================================================
REM  SFU Library - restore files that SETUP moved to this USB.
REM
REM  When you used "Free up space" during setup, your files were copied
REM  here (verified), then deleted from the PC, and logged in
REM  _offloaded\moved_manifest.json. This copies each one back to its
REM  original location, verifies it, then removes the USB copy.
REM ===================================================================
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -Command ". '%HERE%space_assistant.ps1'; $mp = Join-Path '%HERE%' '_offloaded\moved_manifest.json'; if (Test-Path -LiteralPath $mp) { $r = Restore-MovedFiles -ManifestPath $mp -Progress { param($m) Write-Host $m }; Write-Host ''; Write-Host ('Restored ' + $r.restored + ', skipped ' + $r.skipped + ', failed ' + $r.failed) } else { Write-Host 'Nothing to restore (no _offloaded manifest on this drive).' }"
echo.
pause
endlocal
