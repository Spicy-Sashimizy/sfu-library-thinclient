# ============================================================================
#  install_wizard.ps1 - Duck Library (portable social-sciences) setup wizard
#
#  Self-contained WPF wizard. Ships at the bundle root on the USB; launched by
#  SETUP.bat (double-click). Steps:
#     0  Welcome + USB-vs-SSD speed explainer
#     1  CPU preflight (AVX2 / x86-64-v3 - the hard floor for seismic.pyd)
#     2  Mode: Install-to-PC (fastest) / Hybrid / Run-from-USB (sequential queue)
#     3  Free up space  (optional - only if the chosen mode needs more room)
#     4  Copy / progress (determinate; runs off the UI thread)
#     5  Finish + Launch
#
#  It writes sfu_runtime.cfg (consumed by START.bat) and launches the app.
#  Personal-file offload uses space_assistant.ps1's verified copy->delete->undo.
#
#  Windows PowerShell 5.1 compatible. AUTHORED 2026-08-05 on Linux; UNPROVEN on
#  Windows until run there (WPF + P/Invoke + runspaces can only be smoke-tested
#  on a real Windows host).
# ============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms | Out-Null

$script:ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:BundleRoot = $script:ScriptDir           # wizard ships at the bundle root
. (Join-Path $script:ScriptDir 'space_assistant.ps1')

# ── constants / measured facts ──────────────────────────────────────────────
$script:BUNDLE_GIB_APPROX = 66      # measured 2026-08-04 (portable_socsci_verify)
# Runtime parts that benefit from fast local storage (everything except the big
# streamed seismic shards). Hybrid copies these to SSD, leaves seismic on USB.
$script:CommonDirs  = @('thinclient_index', 'models', 'python', 'src', 'web')
$script:CommonFiles = @('START.bat', 'regen_seismic_manifest.py', 'MOVE-BACK.bat', 'space_assistant.ps1')

# ── helpers ─────────────────────────────────────────────────────────────────
function Test-Avx2 {
    # PF_AVX2_INSTRUCTIONS_AVAILABLE = 40 (Windows 10+). Older Windows returns
    # false for unknown feature ids, which correctly degrades to "warn".
    try {
        if (-not ('Win32.CpuFeat' -as [type])) {
            Add-Type -Namespace Win32 -Name CpuFeat -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern bool IsProcessorFeaturePresent(uint feature);
'@ | Out-Null
        }
        return [Win32.CpuFeat]::IsProcessorFeaturePresent(40)
    } catch { return $false }
}

function Get-CpuName {
    try { (Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1).Name } catch { 'unknown CPU' }
}

function Get-DirSizeBytes {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [int64]0 }
    try {
        $sum = (Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
        if ($null -eq $sum) { return [int64]0 }
        return [int64]$sum
    } catch { return [int64]0 }
}

function Get-FreeBytes {
    param([string]$AnyPath)
    try {
        $root = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $AnyPath -ErrorAction SilentlyContinue))
        if (-not $root) { $root = [System.IO.Path]::GetPathRoot($AnyPath) }
        return ([System.IO.DriveInfo]::new($root)).AvailableFreeSpace
    } catch { return [int64]0 }
}

function Format-GiB { param([int64]$Bytes) '{0:N1} GiB' -f ($Bytes / 1GB) }

# ── shared progress state + background runner ───────────────────────────────
$script:sync = [hashtable]::Synchronized(@{
    pct = 0.0; status = ''; done = $false; ok = $true; error = $null; result = $null
    log = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList))
})
function Reset-Sync {
    $script:sync.pct = 0.0; $script:sync.status = ''; $script:sync.done = $false
    $script:sync.ok = $true; $script:sync.error = $null; $script:sync.result = $null
    $script:sync.log.Clear()
}
function Start-Bg {
    param([scriptblock]$Work, [hashtable]$Vars = @{})
    $rs = [runspacefactory]::CreateRunspace()
    $rs.ApartmentState = 'STA'; $rs.ThreadOptions = 'ReuseThread'; $rs.Open()
    $rs.SessionStateProxy.SetVariable('sync', $script:sync)
    $rs.SessionStateProxy.SetVariable('ScriptDir', $script:ScriptDir)
    foreach ($k in $Vars.Keys) { $rs.SessionStateProxy.SetVariable($k, $Vars[$k]) }
    $psx = [powershell]::Create(); $psx.Runspace = $rs
    [void]$psx.AddScript($Work)
    $handle = $psx.BeginInvoke()
    $script:bg = [pscustomobject]@{ ps = $psx; rs = $rs; handle = $handle }
}

# ── copy work (runs in the background runspace) ─────────────────────────────
$script:CopyWork = {
    # Vars injected: $ScriptDir, $Source (bundle root), $Target, $Parts (dirs),
    # $Files (top-level files). Copies with a determinate percent.
    function _log($m) { [void]$sync.log.Add($m) }
    try {
        $items = New-Object System.Collections.Generic.List[object]
        $total = [int64]0
        foreach ($d in $Parts) {
            $sp = Join-Path $Source $d
            if (-not (Test-Path -LiteralPath $sp)) { continue }
            Get-ChildItem -LiteralPath $sp -File -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
                $rel = $_.FullName.Substring($Source.Length).TrimStart('\')
                $items.Add([pscustomobject]@{ src = $_.FullName; rel = $rel; len = $_.Length })
                $total += $_.Length
            }
        }
        foreach ($f in $Files) {
            $sp = Join-Path $Source $f
            if (-not (Test-Path -LiteralPath $sp)) { continue }
            $fi = Get-Item -LiteralPath $sp
            $items.Add([pscustomobject]@{ src = $fi.FullName; rel = $fi.Name; len = $fi.Length })
            $total += $fi.Length
        }
        if ($total -le 0) { $total = 1 }
        $done = [int64]0
        foreach ($it in $items) {
            $dst = Join-Path $Target $it.rel
            $dd = Split-Path -Parent $dst
            if (-not (Test-Path -LiteralPath $dd)) { New-Item -ItemType Directory -Force -Path $dd | Out-Null }
            $sync.status = "Copying $($it.rel)  ($('{0:N1}' -f ($it.len/1GB)) GiB)..."
            Copy-Item -LiteralPath $it.src -Destination $dst -Force
            $done += $it.len
            $sync.pct = [math]::Min(100.0, 100.0 * $done / $total)
        }
        $sync.status = 'Copy complete.'
        $sync.pct = 100.0
        _log "Copied $($items.Count) files ($('{0:N1}' -f ($total/1GB)) GiB) to $Target"
    } catch {
        $sync.ok = $false; $sync.error = $_.Exception.Message
        _log "COPY FAILED: $($_.Exception.Message)"
    } finally {
        $sync.done = $true
    }
}

# ── space-assistant move work (runs in the background runspace) ─────────────
$script:MoveWork = {
    # Vars: $ScriptDir, $Selected (string[] paths), $UsbRoot, $ManifestPath
    function _log($m) { [void]$sync.log.Add($m) }
    try {
        . (Join-Path $ScriptDir 'space_assistant.ps1')
        $n = @($Selected).Count; $i = 0; $freed = [int64]0
        foreach ($p in $Selected) {
            $i++
            $sync.status = "Moving $i of $n: $(Split-Path $p -Leaf)"
            $r = Move-FileVerified -SourcePath $p -UsbRoot $UsbRoot -ManifestPath $ManifestPath -Progress { param($m) $sync.status = $m }
            if ($r.ok) { $freed += $r.size; _log "moved: $($r.orig)" }
            $sync.pct = 100.0 * $i / [math]::Max(1, $n)
        }
        $sync.result = $freed
        $sync.status = "Freed $('{0:N1}' -f ($freed/1GB)) GiB."
    } catch {
        $sync.ok = $false; $sync.error = $_.Exception.Message
        _log "MOVE FAILED: $($_.Exception.Message)"
    } finally {
        $sync.done = $true
    }
}

# ============================================================================
#  XAML
# ============================================================================
[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Duck Library - Setup" Height="640" Width="860"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" Background="#F5F5F7">
  <DockPanel>
    <Border DockPanel.Dock="Top" Background="#B3261E" Padding="24,18">
      <StackPanel>
        <TextBlock x:Name="HdrTitle" Text="Welcome" Foreground="White" FontSize="21" FontWeight="SemiBold"/>
        <TextBlock x:Name="HdrSub" Text="" Foreground="#F6DCDA" FontSize="12" Margin="0,3,0,0" TextWrapping="Wrap"/>
      </StackPanel>
    </Border>
    <Border DockPanel.Dock="Bottom" Background="#ECECEE" Padding="18,12">
      <DockPanel>
        <TextBlock x:Name="StepDots" DockPanel.Dock="Left" VerticalAlignment="Center" Foreground="#777" FontSize="12"/>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right">
          <Button x:Name="BtnBack" Content="Back" Width="96" Height="34" Margin="6,0"/>
          <Button x:Name="BtnNext" Content="Next" Width="140" Height="34" Margin="6,0"
                  Background="#B3261E" Foreground="White" FontWeight="SemiBold" BorderThickness="0"/>
          <Button x:Name="BtnCancel" Content="Cancel" Width="96" Height="34" Margin="6,0"/>
        </StackPanel>
      </DockPanel>
    </Border>
    <Grid Margin="28,22">
      <!-- Step 0: Welcome -->
      <StackPanel x:Name="Step0">
        <TextBlock FontSize="15" TextWrapping="Wrap" Foreground="#222">
          This sets up the offline Duck Library (social-sciences edition) on this computer.
        </TextBlock>
        <Border Background="#FFF6E5" BorderBrush="#E9C46A" BorderThickness="1" CornerRadius="8" Padding="16" Margin="0,18">
          <StackPanel>
            <TextBlock FontWeight="SemiBold" FontSize="14" Text="Speed depends on where the data lives"/>
            <TextBlock TextWrapping="Wrap" Margin="0,8,0,0" Foreground="#444">
              The search index is large (~66 GiB). Running it from the USB stick works, but random
              reads off USB are slow - a cold search was measured at ~112 seconds. Copied to this
              computer's internal drive (SSD), searches are far faster. You'll choose next.
            </TextBlock>
          </StackPanel>
        </Border>
        <TextBlock TextWrapping="Wrap" Foreground="#666" FontSize="12"
                   Text="Nothing is changed on your computer until you pick a mode and confirm."/>
      </StackPanel>

      <!-- Step 1: CPU check -->
      <StackPanel x:Name="Step1" Visibility="Collapsed">
        <TextBlock FontSize="15" Text="Checking this computer's processor..." Foreground="#222"/>
        <Border x:Name="CpuBox" Background="#EAF7EE" BorderBrush="#7FBF8F" BorderThickness="1" CornerRadius="8" Padding="16" Margin="0,16">
          <StackPanel>
            <TextBlock x:Name="CpuResult" FontSize="14" FontWeight="SemiBold" TextWrapping="Wrap"/>
            <TextBlock x:Name="CpuDetail" FontSize="12" Foreground="#444" TextWrapping="Wrap" Margin="0,8,0,0"/>
          </StackPanel>
        </Border>
        <TextBlock x:Name="CpuHelp" FontSize="12" Foreground="#666" TextWrapping="Wrap"/>
      </StackPanel>

      <!-- Step 2: Mode -->
      <StackPanel x:Name="Step2" Visibility="Collapsed">
        <TextBlock FontSize="15" Text="How do you want to run it?" Foreground="#222" FontWeight="SemiBold"/>
        <RadioButton x:Name="RbPc" GroupName="mode" Margin="0,14,0,0" IsChecked="True">
          <StackPanel>
            <TextBlock Text="Install to this PC - fastest" FontWeight="SemiBold" FontSize="14"/>
            <TextBlock x:Name="RbPcSub" Foreground="#555" FontSize="12" TextWrapping="Wrap"/>
          </StackPanel>
        </RadioButton>
        <RadioButton x:Name="RbHybrid" GroupName="mode" Margin="0,12,0,0">
          <StackPanel>
            <TextBlock Text="Hybrid - copy the fast parts, stream the rest from USB" FontWeight="SemiBold" FontSize="14"/>
            <TextBlock x:Name="RbHybridSub" Foreground="#555" FontSize="12" TextWrapping="Wrap"/>
          </StackPanel>
        </RadioButton>
        <RadioButton x:Name="RbUsb" GroupName="mode" Margin="0,12,0,0">
          <StackPanel>
            <TextBlock Text="Run from USB - nothing installed (sequential search queue)" FontWeight="SemiBold" FontSize="14"/>
            <TextBlock x:Name="RbUsbSub" Foreground="#555" FontSize="12" TextWrapping="Wrap"/>
          </StackPanel>
        </RadioButton>
        <Grid Margin="0,18,0,0">
          <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/></Grid.ColumnDefinitions>
          <TextBlock Grid.Column="0" Text="Install to:  " VerticalAlignment="Center" Foreground="#444"/>
          <TextBox x:Name="TargetPath" Grid.Column="1" Height="30" VerticalContentAlignment="Center" Padding="8,0"/>
        </Grid>
        <Button x:Name="BtnBrowse" Content="Browse..." Width="100" Height="28" HorizontalAlignment="Left" Margin="82,8,0,0"/>
        <Border Background="#EEF2F7" CornerRadius="8" Padding="14" Margin="0,16,0,0">
          <TextBlock x:Name="SpaceInfo" FontSize="12" Foreground="#333" TextWrapping="Wrap"/>
        </Border>
      </StackPanel>

      <!-- Step 3: Space assistant -->
      <StackPanel x:Name="Step3" Visibility="Collapsed">
        <TextBlock FontSize="15" FontWeight="SemiBold" Text="Free up space by moving files to the USB" Foreground="#222"/>
        <TextBlock x:Name="SpaceNeed" FontSize="12" Foreground="#B3261E" TextWrapping="Wrap" Margin="0,6,0,0"/>
        <TextBlock FontSize="12" Foreground="#555" TextWrapping="Wrap" Margin="0,6,0,10"
                   Text="Tick files to move to the USB. Each is copied and checksum-verified BEFORE the original is deleted, and recorded so you can move it back later (MOVE-BACK.bat)."/>
        <Border BorderBrush="#CCC" BorderThickness="1" CornerRadius="6" Height="230">
          <ScrollViewer VerticalScrollBarVisibility="Auto">
            <StackPanel x:Name="FileList" Margin="8"/>
          </ScrollViewer>
        </Border>
        <TextBlock x:Name="FreedInfo" FontSize="12" Foreground="#2A7" Margin="0,8,0,0"/>
      </StackPanel>

      <!-- Step 4: Progress -->
      <StackPanel x:Name="Step4" Visibility="Collapsed">
        <TextBlock x:Name="ProgTitle" FontSize="15" FontWeight="SemiBold" Text="Installing..." Foreground="#222"/>
        <ProgressBar x:Name="Prog" Height="22" Minimum="0" Maximum="100" Margin="0,16" Foreground="#B3261E"/>
        <TextBlock x:Name="ProgStatus" FontSize="12" Foreground="#444" TextWrapping="Wrap"/>
        <Border BorderBrush="#DDD" BorderThickness="1" CornerRadius="6" Margin="0,12,0,0" Height="180">
          <ScrollViewer VerticalScrollBarVisibility="Auto">
            <TextBox x:Name="ProgLog" IsReadOnly="True" BorderThickness="0" Background="Transparent"
                     FontFamily="Consolas" FontSize="11" TextWrapping="Wrap"/>
          </ScrollViewer>
        </Border>
      </StackPanel>

      <!-- Step 5: Finish -->
      <StackPanel x:Name="Step5" Visibility="Collapsed">
        <TextBlock FontSize="18" FontWeight="SemiBold" Text="All set." Foreground="#1B7F3B"/>
        <TextBlock x:Name="FinishMsg" FontSize="13" Foreground="#333" TextWrapping="Wrap" Margin="0,12,0,0"/>
        <CheckBox x:Name="ChkLaunch" Content="Launch Duck Library now" IsChecked="True" Margin="0,18,0,0"/>
        <CheckBox x:Name="ChkShortcut" Content="Create a Desktop shortcut" IsChecked="True" Margin="0,8,0,0"/>
      </StackPanel>
    </Grid>
  </DockPanel>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$win = [Windows.Markup.XamlReader]::Load($reader)

# bind named controls into script scope
'HdrTitle','HdrSub','StepDots','BtnBack','BtnNext','BtnCancel',
'Step0','Step1','Step2','Step3','Step4','Step5',
'CpuBox','CpuResult','CpuDetail','CpuHelp',
'RbPc','RbHybrid','RbUsb','RbPcSub','RbHybridSub','RbUsbSub','TargetPath','BtnBrowse','SpaceInfo',
'SpaceNeed','FileList','FreedInfo',
'ProgTitle','Prog','ProgStatus','ProgLog',
'FinishMsg','ChkLaunch','ChkShortcut' | ForEach-Object {
    Set-Variable -Scope script -Name $_ -Value $win.FindName($_)
}

# ── wizard state ────────────────────────────────────────────────────────────
$script:step        = 0
$script:StepPanels  = @($Step0, $Step1, $Step2, $Step3, $Step4, $Step5)
$script:sizeSeismic = $null
$script:sizeHot     = $null
$script:freedBytes  = [int64]0
$script:copyStarted = $false
$script:TargetPath.Text = Join-Path $env:LOCALAPPDATA 'Duck-Library'

function Get-Mode {
    if ($RbPc.IsChecked)     { return 'pc' }
    if ($RbHybrid.IsChecked) { return 'hybrid' }
    return 'usb'
}
function Get-RequiredBytes {
    switch (Get-Mode) {
        'pc'     { return ($script:sizeHot + $script:sizeSeismic) }
        'hybrid' { return $script:sizeHot }
        default  { return [int64]0 }
    }
}
function Test-NeedsSpace {
    if ((Get-Mode) -eq 'usb') { return $false }
    $free = Get-FreeBytes -AnyPath $script:TargetPath.Text
    return ((Get-RequiredBytes) + 2GB) -gt $free      # 2 GiB headroom
}

# ── per-step enter actions ──────────────────────────────────────────────────
function Enter-Step {
    param([int]$i)
    switch ($i) {
        1 {
            $avx2 = Test-Avx2
            $cpu  = Get-CpuName
            if ($avx2) {
                $CpuBox.Background = '#EAF7EE'; $CpuBox.BorderBrush = '#7FBF8F'
                $CpuResult.Text = "OK:  Compatible processor"
                $CpuResult.Foreground = '#1B7F3B'
                $CpuDetail.Text = "$cpu`nAVX2 / x86-64-v3 supported - the search engine (seismic.pyd) will run."
                $CpuHelp.Text = ''
            } else {
                $CpuBox.Background = '#FDECEA'; $CpuBox.BorderBrush = '#E0736A'
                $CpuResult.Text = "!  This processor may not support AVX2"
                $CpuResult.Foreground = '#B3261E'
                $CpuDetail.Text = "$cpu`nThe engine is compiled for x86-64-v3 (AVX2). If it crashes on launch, rebuild seismic.pyd one ISA level lower."
                $CpuHelp.Text = "To rebuild: edit build_windows_runtime.ps1 and change `-C target-cpu=x86-64-v3` to `x86-64-v2` (or plain `x86-64`), then run it again. You can continue setup either way."
            }
        }
        2 {
            if ($null -eq $script:sizeSeismic) {
                $SpaceInfo.Text = 'Measuring bundle size...'
                $win.Dispatcher.Invoke([action]{}, 'Background')
                $script:sizeSeismic = Get-DirSizeBytes (Join-Path $script:BundleRoot 'seismic')
                $hot = [int64]0
                foreach ($d in $script:CommonDirs) { $hot += Get-DirSizeBytes (Join-Path $script:BundleRoot $d) }
                $script:sizeHot = $hot
            }
            $free = Get-FreeBytes -AnyPath $script:TargetPath.Text
            $RbPcSub.Text     = "Copies the whole engine (~$(Format-GiB ($script:sizeHot + $script:sizeSeismic))) to this PC. Best speed."
            $RbHybridSub.Text = "Copies ~$(Format-GiB $script:sizeHot) to this PC, streams the $(Format-GiB $script:sizeSeismic) seismic index from USB. Good speed, less disk."
            $RbUsbSub.Text    = "Runs entirely from the USB. 0 GiB installed. Slowest - turns on the one-at-a-time search queue."
            Update-SpaceInfo
        }
        3 {
            $req  = Get-RequiredBytes
            $free = Get-FreeBytes -AnyPath $script:TargetPath.Text
            $short = [math]::Max(0, ($req + 2GB) - $free)
            $SpaceNeed.Text = "You need about $(Format-GiB $short) more free on $([System.IO.Path]::GetPathRoot($script:TargetPath.Text)) for this mode. Pick files to move to the USB."
            Populate-FileList
        }
        4 {
            $ProgTitle.Text = if ((Get-Mode) -eq 'usb') { 'Preparing...' } else { 'Installing...' }
            Start-CopyPhase
        }
        5 {
            $m = Get-Mode
            $where = if ($m -eq 'usb') { 'the USB drive' } else { $script:TargetPath.Text }
            $note = switch ($m) {
                'pc'     { 'The engine is fully on this PC - fastest searches.' }
                'hybrid' { 'Fast parts are on this PC; the seismic index streams from the USB (keep it plugged in).' }
                default  { 'Running from the USB. Searches run one at a time (search queue is ON). Keep the USB plugged in.' }
            }
            $FinishMsg.Text = "Duck Library is ready at:`n$where`n`n$note"
        }
    }
}

function Update-SpaceInfo {
    $free = Get-FreeBytes -AnyPath $script:TargetPath.Text
    $req  = Get-RequiredBytes
    $root = [System.IO.Path]::GetPathRoot($script:TargetPath.Text)
    if ((Get-Mode) -eq 'usb') {
        $SpaceInfo.Text = "Run-from-USB needs no free space on this PC. $root has $(Format-GiB $free) free."
    } else {
        $fit = if (($req + 2GB) -le $free) { 'fits' } else { 'NOT enough - the next step can free space' }
        $SpaceInfo.Text = "This mode needs ~$(Format-GiB $req).  $root has $(Format-GiB $free) free  ->  $fit."
    }
}

function Populate-FileList {
    $FileList.Children.Clear()
    $files = Get-LargeUserFiles -MinSizeMB 200
    if (@($files).Count -eq 0) {
        $tb = New-Object System.Windows.Controls.TextBlock
        $tb.Text = 'No large files (>200 MB) found in Downloads/Videos/Documents/Desktop. You can Browse to your target and free space manually, or choose Hybrid / Run-from-USB.'
        $tb.TextWrapping = 'Wrap'; $tb.Foreground = '#B3261E'
        $FileList.Children.Add($tb) | Out-Null
        return
    }
    foreach ($f in $files) {
        $cb = New-Object System.Windows.Controls.CheckBox
        $cb.Content = "{0}   -   {1:N2} GiB" -f $f.Name, ($f.Size/1GB)
        $cb.Tag = $f.Path
        $cb.Margin = '2'
        $cb.ToolTip = $f.Path
        $FileList.Children.Add($cb) | Out-Null
    }
}

# ── copy / move orchestration via DispatcherTimer ───────────────────────────
$script:timer = New-Object System.Windows.Threading.DispatcherTimer
$script:timer.Interval = [TimeSpan]::FromMilliseconds(200)
$script:timer.Add_Tick({
    try { $Prog.Value = [double]$script:sync.pct } catch {}
    try { $ProgStatus.Text = [string]$script:sync.status } catch {}
    try {
        if ($script:sync.log.Count -gt 0) {
            $lines = @($script:sync.log.ToArray()); $script:sync.log.Clear()
            $ProgLog.AppendText(($lines -join "`r`n") + "`r`n"); $ProgLog.ScrollToEnd()
        }
    } catch {}
    if ($script:sync.done) {
        $script:timer.Stop()
        if (-not $script:sync.ok) {
            [System.Windows.MessageBox]::Show("Operation failed:`n$($script:sync.error)", 'Duck Library Setup',
                'OK', 'Error') | Out-Null
            $BtnNext.IsEnabled = $true; $BtnBack.IsEnabled = $true
        } else {
            $BtnNext.IsEnabled = $true
            $BtnNext.Content = 'Next'
            $script:copyStarted = $false
            # auto-advance from the copy step to Finish
            if ($script:step -eq 4) { Go-Step 5 }
        }
    }
})

function Start-CopyPhase {
    Reset-Sync
    $ProgLog.Clear()
    $BtnNext.IsEnabled = $false; $BtnBack.IsEnabled = $false
    $m = Get-Mode
    if ($m -eq 'usb') {
        $script:sync.status = 'Nothing to copy - will run from the USB.'
        $script:sync.pct = 100.0; $script:sync.done = $true
        $script:timer.Start(); return
    }
    $parts = @($script:CommonDirs)
    if ($m -eq 'pc') { $parts += 'seismic' }
    $target = $script:TargetPath.Text
    if (-not (Test-Path -LiteralPath $target)) { New-Item -ItemType Directory -Force -Path $target | Out-Null }
    Start-Bg -Work $script:CopyWork -Vars @{
        Source = $script:BundleRoot; Target = $target; Parts = $parts; Files = $script:CommonFiles
    }
    $script:timer.Start()
}

function Start-MovePhase {
    # gather checked files
    $sel = @()
    foreach ($c in $FileList.Children) {
        if ($c -is [System.Windows.Controls.CheckBox] -and $c.IsChecked -and $c.Tag) { $sel += [string]$c.Tag }
    }
    if ($sel.Count -eq 0) {
        [System.Windows.MessageBox]::Show('No files selected. Tick files to move, or go Back and choose Hybrid / Run-from-USB.',
            'Duck Library Setup', 'OK', 'Information') | Out-Null
        return $false
    }
    Reset-Sync
    $BtnNext.IsEnabled = $false; $BtnBack.IsEnabled = $false
    $manifest = Get-OffloadManifestPath -UsbRoot $script:BundleRoot
    # reuse the progress step UI region for feedback
    Start-Bg -Work $script:MoveWork -Vars @{ Selected = $sel; UsbRoot = $script:BundleRoot; ManifestPath = $manifest }
    # poll inline (moves are usually few) with a short modal-ish wait via timer
    $script:mt = New-Object System.Windows.Threading.DispatcherTimer
    $script:mt.Interval = [TimeSpan]::FromMilliseconds(200)
    $script:mt.Add_Tick({
        $FreedInfo.Text = [string]$script:sync.status
        if ($script:sync.done) {
            $script:mt.Stop()
            if ($script:sync.ok) {
                $script:freedBytes += [int64]($script:sync.result)
                $BtnBack.IsEnabled = $true; $BtnNext.IsEnabled = $true
                if (Test-NeedsSpace) {
                    $FreedInfo.Text = "Freed $(Format-GiB $script:freedBytes), but still short - select more files."
                    Populate-FileList
                } else {
                    $FreedInfo.Text = "Freed enough. Click Next to install."
                }
            } else {
                [System.Windows.MessageBox]::Show("Move failed:`n$($script:sync.error)",'Duck Library Setup','OK','Error') | Out-Null
                $BtnBack.IsEnabled = $true; $BtnNext.IsEnabled = $true
            }
        }
    })
    $script:mt.Start()
    return $true
}

# ── config write + launch ───────────────────────────────────────────────────
function Write-RuntimeConfig {
    $m = Get-Mode
    if ($m -eq 'usb') {
        $runRoot = $script:BundleRoot; $seismicBundle = $script:BundleRoot; $seq = 1
    } elseif ($m -eq 'hybrid') {
        $runRoot = $script:TargetPath.Text; $seismicBundle = $script:BundleRoot; $seq = 0
    } else {
        $runRoot = $script:TargetPath.Text; $seismicBundle = $script:TargetPath.Text; $seq = 0
    }
    $cfg = @(
        "MODE=$m"
        "SEQUENTIAL=$seq"
        "INDEX_ROOT=$(Join-Path $runRoot 'thinclient_index')"
        "MODEL_ROOT=$(Join-Path $runRoot 'models')"
        "SEISMIC_BUNDLE_ROOT=$seismicBundle"
    ) -join "`r`n"
    $cfgPath = Join-Path $runRoot 'sfu_runtime.cfg'
    Set-Content -LiteralPath $cfgPath -Value $cfg -Encoding ASCII
    return $runRoot
}
function New-DesktopShortcut {
    param([string]$StartBat)
    try {
        $desktop = [Environment]::GetFolderPath('Desktop')
        $lnk = Join-Path $desktop 'Duck Library.lnk'
        $sh = New-Object -ComObject WScript.Shell
        $s = $sh.CreateShortcut($lnk)
        $s.TargetPath = $StartBat
        $s.WorkingDirectory = Split-Path -Parent $StartBat
        $s.IconLocation = "$env:SystemRoot\System32\imageres.dll,3"
        $s.Description = 'Duck Library (offline social-sciences edition)'
        $s.Save()
    } catch {}
}
function Complete-Setup {
    $runRoot = Write-RuntimeConfig
    $startBat = Join-Path $runRoot 'START.bat'
    if ($ChkShortcut.IsChecked) { New-DesktopShortcut -StartBat $startBat }
    if ($ChkLaunch.IsChecked -and (Test-Path -LiteralPath $startBat)) {
        Start-Process -FilePath $startBat -WorkingDirectory $runRoot
    }
}

# ── navigation ──────────────────────────────────────────────────────────────
function Next-Index {
    param([int]$from)
    # 2 -> 3 only if space is needed; else 2 -> 4. 3 -> 4. others +1.
    switch ($from) {
        2 { if (Test-NeedsSpace) { return 3 } else { return 4 } }
        default { return $from + 1 }
    }
}
function Prev-Index {
    param([int]$to)
    if ($to -eq 4) { if (Test-NeedsSpace) { return 3 } else { return 2 } }
    if ($to -eq 3) { return 2 }
    return [math]::Max(0, $to - 1)
}
function Go-Step {
    param([int]$i)
    $script:step = $i
    for ($k = 0; $k -lt $script:StepPanels.Count; $k++) {
        $script:StepPanels[$k].Visibility = if ($k -eq $i) { 'Visible' } else { 'Collapsed' }
    }
    $titles = @(
        @('Welcome',                 'Offline Duck Library - social-sciences edition'),
        @('Step 1 of 4 - Processor', 'Confirming this computer can run the engine'),
        @('Step 2 of 4 - Choose mode','Install to PC, Hybrid, or run from USB'),
        @('Free up space',           'Move files to the USB to make room'),
        @('Working...',                'Please wait'),
        @('Finished',                'Setup complete')
    )
    $HdrTitle.Text = $titles[$i][0]; $HdrSub.Text = $titles[$i][1]
    $StepDots.Text = "$([char]0x2022) " * ($i + 1)
    $BtnBack.IsEnabled = ($i -gt 0 -and $i -ne 4)
    $BtnNext.Visibility = if ($i -eq 4) { 'Collapsed' } else { 'Visible' }
    $BtnNext.Content = if ($i -eq 2) { 'Install' } elseif ($i -eq 5) { 'Finish' } else { 'Next' }
    $BtnCancel.Content = if ($i -eq 5) { 'Close' } else { 'Cancel' }
    Enter-Step $i
}

$BtnBrowse.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = 'Choose where to install Duck Library'
    if ($dlg.ShowDialog() -eq 'OK') {
        $script:TargetPath.Text = Join-Path $dlg.SelectedPath 'Duck-Library'
        Update-SpaceInfo
    }
})
$RbPc.Add_Checked({ Update-SpaceInfo }); $RbHybrid.Add_Checked({ Update-SpaceInfo }); $RbUsb.Add_Checked({ Update-SpaceInfo })
$TargetPath.Add_LostFocus({ Update-SpaceInfo })

$BtnBack.Add_Click({ if ($script:step -gt 0) { Go-Step (Prev-Index $script:step) } })
$BtnCancel.Add_Click({ $win.Close() })
$BtnNext.Add_Click({
    switch ($script:step) {
        2 {
            # entering install: if space is needed, go to assistant; else copy.
            Go-Step (Next-Index 2)
        }
        3 {
            if (-not (Test-NeedsSpace)) { Go-Step 4 }   # already enough room -> install
            else { [void](Start-MovePhase) }            # need room -> verified move (async)
        }
        5 {
            Complete-Setup
            $win.Close()
        }
        default { Go-Step (Next-Index $script:step) }
    }
})

Go-Step 0
$win.Topmost = $true; $win.Add_ContentRendered({ $win.Topmost = $false }) | Out-Null
[void]$win.ShowDialog()
