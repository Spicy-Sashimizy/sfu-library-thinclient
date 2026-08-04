<#
  build_windows_runtime.ps1 — complete the portable social-sciences bundle on Windows.

  Run this ONCE on a Windows x86-64 PC that has Rust (cargo) installed, ideally
  with the thumb drive plugged in so it builds in place. It produces, on the drive:

      python\                      relocatable CPython (self-contained) + CPU wheels
      python\...\seismic.pyd       the maturin build of the 5a-cfg-gated fork

  After it succeeds, double-clicking START.bat serves the library offline.

  Prereqs on THIS PC:
    - Rust toolchain (https://rustup.rs)  — needed to compile seismic.pyd
    - Internet (for the relocatable Python + the CPU serving wheels; the RUST
      deps are vendored in build\vendor so the cargo build itself is offline)

  Layout it expects (staged by scripts/portable_socsci/06_windows_buildkit.py):
    <root>\build\seismic_upstream\  (fork source + .cargo\config.toml -> ..\vendor)
    <root>\build\vectorium_fork\    <root>\build\toolkit_fork\
    <root>\build\vendor\            (vendored crates.io + git deps; offline build)
    <root>\build\serving_requirements_win.txt
    <root>\src\  <root>\web\  <root>\thinclient_index\  <root>\seismic\  <root>\models\

  Env overrides: PY_STANDALONE_URL (relocatable python tarball), PY_TAG/PY_VER.
#>
[CmdletBinding()]
param([string]$Root = $PSScriptRoot)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = (Resolve-Path $Root).Path
Write-Host "[build] bundle root: $Root"

# Portable ISA only — never target-cpu=native (spike/CLAUDE.md rule).
$env:RUSTFLAGS = "-C target-cpu=x86-64-v3"

# ── 1. cargo present? ────────────────────────────────────────────────────────
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
  throw "cargo (Rust) not found on PATH. Install from https://rustup.rs then re-run."
}
Write-Host "[build] cargo: $((cargo --version))"

# ── 2. relocatable CPython on the drive (self-contained, so the end user needs
#       nothing installed). python-build-standalone 'install_only' build. ──────
$PyDir  = Join-Path $Root "python"
$PyExe  = Join-Path $PyDir "python.exe"
if (-not (Test-Path $PyExe)) {
  $PyVer = if ($env:PY_VER) { $env:PY_VER } else { "3.11.9" }
  $PyTag = if ($env:PY_TAG) { $env:PY_TAG } else { "20240814" }
  $url = if ($env:PY_STANDALONE_URL) { $env:PY_STANDALONE_URL } else {
    "https://github.com/astral-sh/python-build-standalone/releases/download/" +
    "$PyTag/cpython-$PyVer+$PyTag-x86_64-pc-windows-msvc-install_only.tar.gz" }
  Write-Host "[build] fetching relocatable CPython $PyVer -> python\ ..."
  $tgz = Join-Path $env:TEMP "cpython-portable.tar.gz"
  Invoke-WebRequest -Uri $url -OutFile $tgz
  tar -xzf $tgz -C $Root          # extracts a 'python\' dir (install_only layout)
  Remove-Item $tgz -Force
  if (-not (Test-Path $PyExe)) {
    throw "python.exe not found after extract at $PyExe. If the URL 404'd, set " +
          "PY_STANDALONE_URL to a valid python-build-standalone install_only tarball."
  }
}
Write-Host "[build] python: $((& $PyExe --version))"

# ── 3. pip + maturin in that python ──────────────────────────────────────────
& $PyExe -m ensurepip --upgrade 2>$null
& $PyExe -m pip install --upgrade pip maturin
if ($LASTEXITCODE -ne 0) { throw "pip/maturin install failed" }

# ── 4. build seismic.pyd via maturin (offline cargo build over vendored deps) ─
$fork = Join-Path $Root "build\seismic_upstream"
if (-not (Test-Path (Join-Path $fork "Cargo.toml"))) {
  throw "fork source not found at $fork — run 06_windows_buildkit.py first."
}
$wheelOut = Join-Path $Root "build\wheels_built"
Write-Host "[build] maturin build --release (offline, vendored) ..."
Push-Location $fork
try {
  & $PyExe -m maturin build --release --offline -i $PyExe -o $wheelOut
  if ($LASTEXITCODE -ne 0) { throw "maturin build failed" }
} finally { Pop-Location }

# ── 5. install the built seismic wheel + the CPU serving wheels into python\ ──
Write-Host "[build] installing seismic + serving wheels ..."
& $PyExe -m pip install (Get-ChildItem $wheelOut -Filter *.whl | Select-Object -First 1).FullName
$reqs = Join-Path $Root "build\serving_requirements_win.txt"
& $PyExe -m pip install --only-binary=:all: -r $reqs
if ($LASTEXITCODE -ne 0) { throw "serving-wheel install failed" }

# ── 6. verify the import surface loads ───────────────────────────────────────
Write-Host "[build] verifying imports ..."
& $PyExe -c "import seismic, onnxruntime, tantivy, numpy, zstandard, starlette, uvicorn; print('OK: seismic', seismic.__file__)"
if ($LASTEXITCODE -ne 0) { throw "import verification failed" }

Write-Host ""
Write-Host "[build] DONE. The drive is now self-contained." -ForegroundColor Green
Write-Host "[build] Double-click START.bat to launch the SFU Library." -ForegroundColor Green
