# kanban-auto-subscribe installer for Windows (PowerShell 5.1+ / PowerShell 7+)
#
# Usage:
#   .\install.ps1
#   .\install.ps1 -Force
#   .\install.ps1 -Uninstall
#   .\install.ps1 -NoDeps
#   .\install.ps1 -Enable
#
# If execution policy blocks the script, run:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Uninstall,
    [switch]$NoDeps,
    [switch]$Enable,
    [switch]$NoEnable,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

$Tag        = 'kanban-auto-subscribe'
$PluginName = 'kanban-auto-subscribe'

function Write-Log  { param($m) Write-Host "[$Tag] $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "[$Tag] $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "[$Tag] $m" -ForegroundColor Yellow }
function Write-Err  { param($m) Write-Host "[$Tag] $m" -ForegroundColor Red }
function Die        { param($m) Write-Err $m; exit 1 }

if ($Help) {
    @"
$Tag installer (Windows)

Usage: .\install.ps1 [options]

Options:
  -Force        Overwrite an existing installation (old copy is backed up)
  -Uninstall    Remove the plugin
  -NoDeps       Skip the Python / Hermes preflight checks
  -Enable       Enable the plugin without prompting
  -NoEnable     Install without enabling
  -Help         Show this help
"@ | Write-Host
    exit 0
}

# ── Locate the script and the plugin source ─────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SrcDir    = Join-Path $ScriptDir $PluginName

if (-not (Test-Path $SrcDir)) {
    Die "Plugin source not found: $SrcDir`nRun this script from a full clone of the repository."
}

# ── Locate the Hermes plugin directory ──────────────────────────────────────
if ($env:HERMES_HOME) {
    $HermesHome = $env:HERMES_HOME
} else {
    $HermesHome = Join-Path $env:USERPROFILE '.hermes'
}
$PluginDir = Join-Path $HermesHome 'plugins'
$DestDir   = Join-Path $PluginDir $PluginName

# ── Uninstall ───────────────────────────────────────────────────────────────
if ($Uninstall) {
    if (Test-Path $DestDir) {
        Remove-Item -Recurse -Force $DestDir
        Write-Ok "Uninstalled: $DestDir"
        Write-Log "State DB left in place: $(Join-Path $HermesHome "plugin-data\$PluginName")"
    } else {
        Write-Warn "Not installed: $DestDir"
    }
    exit 0
}

# ── Preflight ───────────────────────────────────────────────────────────────
if (-not $NoDeps) {
    $hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($hermesCmd) {
        Write-Ok "Hermes CLI found: $($hermesCmd.Source)"
    } else {
        Write-Warn "hermes not found in PATH - install it before enabling the plugin."
    }

    # Hermes needs Python 3.11+. The 'py' launcher is the reliable way to test on Windows.
    $pyExe = $null
    foreach ($candidate in @('py', 'python', 'python3')) {
        $c = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($c) { $pyExe = $c.Source; break }
    }
    if ($pyExe) {
        try {
            $ver = & $pyExe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($ver -match '^(\d+)\.(\d+)$') {
                $major = [int]$Matches[1]; $minor = [int]$Matches[2]
                if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
                    Write-Warn "Python $ver found, but Hermes needs 3.11+."
                } else {
                    Write-Ok "Python $ver detected ($pyExe)"
                }
            }
        } catch {
            Write-Warn "Could not determine the Python version from '$pyExe'."
        }
    } else {
        Write-Warn "No Python found in PATH. Hermes itself needs Python 3.11+."
    }

    # Home channel: the plugin is a no-op without one.
    $homeChannelFound = $false
    foreach ($f in @((Join-Path $HermesHome '.env'), (Join-Path $HermesHome 'config.yaml'))) {
        if (Test-Path $f) {
            if (Select-String -Path $f -Pattern '^[A-Z0-9_]*_HOME_CHANNEL=' -Quiet -ErrorAction SilentlyContinue) {
                $homeChannelFound = $true
                break
            }
        }
    }
    if ($homeChannelFound) {
        Write-Ok "A home channel is configured"
    } else {
        Write-Warn "No *_HOME_CHANNEL found in $HermesHome."
        Write-Warn "The plugin does nothing until a platform has a home channel"
        Write-Warn "(use /sethome from the chat, or set e.g. TELEGRAM_HOME_CHANNEL in .env)."
    }
} else {
    Write-Warn "Skipping preflight checks (-NoDeps)"
}

# ── Back up an existing installation ────────────────────────────────────────
if (-not (Test-Path $PluginDir)) { New-Item -ItemType Directory -Path $PluginDir -Force | Out-Null }

if (Test-Path $DestDir) {
    $doOverwrite = $false
    if ($Force) {
        $doOverwrite = $true
    } else {
        $ans = Read-Host "[$Tag] Already installed at: $DestDir`nOverwrite? Existing files will be backed up. [y/N]"
        if ($ans -match '^[Yy]') { $doOverwrite = $true } else { Die "Aborted by user" }
    }
    if ($doOverwrite) {
        $stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backup = "$DestDir.backup.$stamp"
        Move-Item $DestDir $backup
        Write-Ok "Existing installation backed up to: $backup"
    }
}

# ── Copy the plugin ─────────────────────────────────────────────────────────
Write-Log "Installing plugin to: $DestDir"
Copy-Item -Recurse -Force $SrcDir $DestDir
# Drop any local bytecode cache copied along (cp -R equivalent has no exclude flag).
Get-ChildItem -Path $DestDir -Recurse -Force -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $DestDir -Recurse -Force -File -Filter '*.pyc' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
Write-Ok "Files copied"

# ── Verify ──────────────────────────────────────────────────────────────────
Write-Log "Verifying installation..."
$missing = @()
foreach ($f in @('plugin.yaml', '__init__.py', 'auto_subscribe.py')) {
    if (-not (Test-Path (Join-Path $DestDir $f))) { $missing += $f }
}
if ($missing.Count -gt 0) {
    Die "Installation incomplete; missing: $($missing -join ', ')"
}

# The manifest name must match the directory or Hermes keys the plugin differently.
$manifestName = (Select-String -Path (Join-Path $DestDir 'plugin.yaml') -Pattern '^name:\s*(.+)$' |
    Select-Object -First 1).Matches[0].Groups[1].Value.Trim()
if ($manifestName -ne $PluginName) {
    Die "plugin.yaml declares name '$manifestName' but the directory is '$PluginName'."
}
Write-Ok "All files present; manifest name matches"

# ── Enable ──────────────────────────────────────────────────────────────────
$shouldEnable = $false
if ($Enable) {
    $shouldEnable = $true
} elseif (-not $NoEnable) {
    if (Get-Command hermes -ErrorAction SilentlyContinue) {
        $ans = Read-Host "[$Tag] Enable the plugin now? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($ans) -or $ans -match '^[Yy]') { $shouldEnable = $true }
    }
}

if ($shouldEnable) {
    if (Get-Command hermes -ErrorAction SilentlyContinue) {
        try {
            & hermes plugins enable $PluginName
            Write-Ok "Plugin enabled"
        } catch {
            Write-Warn "Could not enable automatically. Run: hermes plugins enable $PluginName"
        }
    } else {
        Write-Warn "hermes not in PATH. Run: hermes plugins enable $PluginName"
    }
} else {
    Write-Log "Plugin installed but not enabled."
    Write-Log "Run: hermes plugins enable $PluginName"
}

# ── Done ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[$Tag] installed" -ForegroundColor Green
Write-Host ""
Write-Host "  Plugin dir:  $DestDir"
Write-Host "  Hermes home: $HermesHome"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart the gateway so the plugin loads:"
Write-Host "       hermes gateway restart"
Write-Host "  2. Watch it work (one line per board that had cards to subscribe):"
Write-Host "       Select-String -Path `"$HermesHome\logs\gateway.log`" -Pattern '$PluginName'"
Write-Host "  3. Confirm the subscriptions:"
Write-Host "       hermes kanban notify-list"
Write-Host ""
Write-Host "To preview before writing anything, set dry_run to true in"
Write-Host "  $HermesHome\config.yaml"
Write-Host "    plugins.entries.$PluginName.settings.dry_run"
Write-Host ""
Write-Host "Docs:  https://github.com/metaone01/hermes-kanban-auto-subscribe"
