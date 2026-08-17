# ============================================================================
#  space_assistant.ps1 — verified file offload (laptop -> USB) with undo
#
#  Safe primitive used by install_wizard.ps1's "Free up space" step. To make
#  room on a small SSD for the search engine, the user hand-picks large personal
#  files (movies, downloads) and each one is moved with this contract:
#
#      1. sha256 the original
#      2. copy it to <USB>\_offloaded\<drive>\<original path>
#      3. sha256 the copy and REQUIRE it to match
#      4. only THEN delete the original
#      5. record the move in _offloaded\moved_manifest.json
#
#  Delete is ALWAYS last, so an interruption never destroys data — the worst
#  case is a verified duplicate left on the USB. Restore-MovedFiles reverses it
#  (copy back -> verify -> remove the USB copy), so nothing is one-way.
#
#  Windows PowerShell 5.1 compatible (Get-FileHash / ConvertTo-Json ship in-box).
#  AUTHORED 2026-08-05 on Linux; UNPROVEN on Windows until run there.
# ============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-OffloadManifestPath {
    param([Parameter(Mandatory)][string]$UsbRoot)
    Join-Path $UsbRoot '_offloaded\moved_manifest.json'
}

function Read-OffloadManifest {
    param([Parameter(Mandatory)][string]$ManifestPath)
    if (Test-Path -LiteralPath $ManifestPath) {
        try {
            $m = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            # Normalise .moves to an array (ConvertFrom-Json collapses 0/1 items).
            $moves = @()
            if ($m.PSObject.Properties.Name -contains 'moves' -and $null -ne $m.moves) {
                $moves = @($m.moves)
            }
            return [pscustomobject]@{ version = 1; moves = $moves }
        } catch {
            # Corrupt/partial manifest: do NOT clobber it — surface the error so the
            # caller can back it up rather than silently start a fresh one.
            throw "offload manifest unreadable ($ManifestPath): $($_.Exception.Message)"
        }
    }
    [pscustomobject]@{ version = 1; moves = @() }
}

function Write-OffloadManifest {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$ManifestPath
    )
    $dir = Split-Path -Parent $ManifestPath
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    # Write to a temp then move into place so a crash mid-write can't corrupt the
    # ledger that tells us what was deleted.
    $tmp = "$ManifestPath.tmp"
    ($Manifest | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $ManifestPath -Force
}

function Get-LargeUserFiles {
    <#
      Enumerate candidate files to offload. Scans the given roots (default: the
      current user's Downloads/Videos/Documents/Desktop) and returns files at or
      above -MinSizeMB, largest first. Metadata-only (no hashing here) so it stays
      fast even over big folders.
    #>
    param(
        [string[]]$Roots,
        [int]$MinSizeMB = 200
    )
    if (-not $Roots -or $Roots.Count -eq 0) {
        $up = [Environment]::GetFolderPath('UserProfile')
        $Roots = @(
            (Join-Path $up 'Downloads'),
            (Join-Path $up 'Videos'),
            (Join-Path $up 'Documents'),
            (Join-Path $up 'Desktop')
        )
    }
    $min = [int64]$MinSizeMB * 1MB
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($r in $Roots) {
        if (-not (Test-Path -LiteralPath $r)) { continue }
        try {
            Get-ChildItem -LiteralPath $r -File -Recurse -Force -ErrorAction SilentlyContinue |
                Where-Object { $_.Length -ge $min } |
                ForEach-Object {
                    $out.Add([pscustomobject]@{
                        Path    = $_.FullName
                        Name    = $_.Name
                        Size    = $_.Length
                        SizeGiB = [math]::Round($_.Length / 1GB, 2)
                        Folder  = $r
                    })
                }
        } catch { }
    }
    ,@($out | Sort-Object -Property Size -Descending)
}

function Move-FileVerified {
    <#
      Move ONE file laptop->USB with copy->verify->delete. Returns a status object
      on success; throws (leaving the original intact) on any verification failure.
    #>
    param(
        [Parameter(Mandatory)][string]$SourcePath,
        [Parameter(Mandatory)][string]$UsbRoot,
        [Parameter(Mandatory)][string]$ManifestPath,
        [scriptblock]$Progress
    )
    function _say([string]$m) { if ($Progress) { & $Progress $m } }

    if (-not (Test-Path -LiteralPath $SourcePath)) { throw "source not found: $SourcePath" }
    $src = Get-Item -LiteralPath $SourcePath -Force

    # Mirror the original path under _offloaded so a restore is unambiguous:
    #   C:\Users\me\Videos\a.mkv -> <USB>\_offloaded\C\Users\me\Videos\a.mkv
    $colon = $src.FullName.IndexOf(':')
    if ($colon -lt 1) { throw "unsupported (UNC?) source path: $($src.FullName)" }
    $drive = $src.FullName.Substring(0, $colon)                       # e.g. C
    $tail  = $src.FullName.Substring($colon + 1).TrimStart('\')       # Users\me\Videos\a.mkv
    $destDir = Join-Path (Join-Path (Join-Path $UsbRoot '_offloaded') $drive) (Split-Path $tail -Parent)
    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    }
    $destPath = Join-Path $destDir $src.Name

    _say "Hashing $($src.Name)..."
    $srcHash = (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash

    _say "Copying $($src.Name) to USB..."
    Copy-Item -LiteralPath $SourcePath -Destination $destPath -Force

    _say "Verifying copy..."
    $dstHash = (Get-FileHash -LiteralPath $destPath -Algorithm SHA256).Hash
    if ($dstHash -ne $srcHash) {
        Remove-Item -LiteralPath $destPath -Force -ErrorAction SilentlyContinue
        throw "checksum mismatch for $($src.Name) — original left intact, bad copy removed"
    }

    # Record the move BEFORE deleting, so the ledger can never lag the deletion.
    $manifest = Read-OffloadManifest -ManifestPath $ManifestPath
    $entry = [pscustomobject]@{
        orig     = $src.FullName
        dest     = $destPath
        size     = $src.Length
        sha256   = $srcHash
        movedUtc = (Get-Date).ToUniversalTime().ToString('o')
        restored = $false
    }
    $manifest.moves = @($manifest.moves) + $entry
    Write-OffloadManifest -Manifest $manifest -ManifestPath $ManifestPath

    _say "Removing original (verified copy is on the USB)..."
    Remove-Item -LiteralPath $SourcePath -Force

    [pscustomobject]@{ ok = $true; orig = $src.FullName; dest = $destPath; size = $src.Length }
}

function Restore-MovedFiles {
    <#
      Undo: for every not-yet-restored move, copy the USB copy back to its original
      path, verify it, then remove the USB copy. Never deletes the USB copy until
      the restored file verifies. Returns counts.
    #>
    param(
        [Parameter(Mandatory)][string]$ManifestPath,
        [scriptblock]$Progress
    )
    function _say([string]$m) { if ($Progress) { & $Progress $m } }

    $manifest = Read-OffloadManifest -ManifestPath $ManifestPath
    $moves = @($manifest.moves)
    $restored = 0; $skipped = 0; $failed = 0
    foreach ($m in $moves) {
        if ($m.restored) { $skipped++; continue }
        if (-not (Test-Path -LiteralPath $m.dest)) {
            _say "Missing USB copy for $($m.orig) — skipping."
            $failed++; continue
        }
        try {
            $origDir = Split-Path -Parent $m.orig
            if (-not (Test-Path -LiteralPath $origDir)) {
                New-Item -ItemType Directory -Force -Path $origDir | Out-Null
            }
            _say "Restoring $(Split-Path $m.orig -Leaf)..."
            Copy-Item -LiteralPath $m.dest -Destination $m.orig -Force
            $h = (Get-FileHash -LiteralPath $m.orig -Algorithm SHA256).Hash
            if ($h -ne $m.sha256) {
                _say "Restore checksum mismatch for $($m.orig) — USB copy kept."
                $failed++; continue
            }
            Remove-Item -LiteralPath $m.dest -Force -ErrorAction SilentlyContinue
            $m.restored = $true
            $restored++
        } catch {
            _say "Restore failed for $($m.orig): $($_.Exception.Message)"
            $failed++
        }
    }
    $manifest.moves = $moves
    Write-OffloadManifest -Manifest $manifest -ManifestPath $ManifestPath
    [pscustomobject]@{ restored = $restored; skipped = $skipped; failed = $failed }
}
