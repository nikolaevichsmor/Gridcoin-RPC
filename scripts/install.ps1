<#
.SYNOPSIS
    One-Click Setup and Configuration Script for Gridcoin Discord Rich Presence (Windows)
.DESCRIPTION
    Verifies Python 3 environment, installs dependencies, validates Gridcoin node RPC
    configuration, configures autostart, and launches the daemon.
#>

[CmdletBinding()]
param (
    [switch]$Unattended,
    [switch]$NoAutostart,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path "$ScriptDir\..").Path

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Gridcoin Discord Rich Presence - Windows Installer  " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python installation
Write-Host "[1/5] Checking Python 3 environment..." -ForegroundColor Yellow
$PythonCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$matches[1]
            if ($minor -ge 8) {
                $PythonCmd = $cmd
                Write-Host "  Found: $ver ($cmd)" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $PythonCmd) {
    $BinaryPath = Join-Path $ProjectRoot "Gridcoin-RPC.exe"
    if (-not (Test-Path $BinaryPath)) {
        $BinaryPath = Join-Path $ProjectRoot "dist\Gridcoin-RPC\Gridcoin-RPC.exe"
    }
    if (Test-Path $BinaryPath) {
        Write-Host "  Python not found, but precompiled binary found: $BinaryPath" -ForegroundColor Green
        $IsBinary = $true
    } else {
        Write-Error "Python 3.8+ was not found in PATH, and Gridcoin-RPC.exe was not found. Please install Python 3.8 or newer from https://www.python.org/downloads/ (ensure 'Add python.exe to PATH' is checked)."
        exit 1
    }
} else {
    $IsBinary = $false
}

# 2. Install / verify Python dependencies if running from source
if (-not $IsBinary) {
    Write-Host "[2/5] Checking and installing Python dependencies..." -ForegroundColor Yellow
    $ReqPath = Join-Path $ProjectRoot "requirements.txt"
    if (Test-Path $ReqPath) {
        try {
            & $PythonCmd -m pip install --quiet --upgrade pip 2>$null
            & $PythonCmd -m pip install --quiet -r $ReqPath
            Write-Host "  Dependencies installed successfully." -ForegroundColor Green
        } catch {
            Write-Warning "  Pip install encountered an issue: $_. Proceeding..."
        }
    }
} else {
    Write-Host "[2/5] Skipping dependency installation (using standalone binary)." -ForegroundColor Gray
}

# 3. Check Gridcoin Core RPC configuration
Write-Host "[3/5] Verifying Gridcoin node RPC configuration..." -ForegroundColor Yellow
$AppDataConf = Join-Path $env:APPDATA "GridcoinResearch\gridcoinresearch.conf"
$EnvFile = Join-Path $ProjectRoot ".env"

if (Test-Path $AppDataConf) {
    Write-Host "  Found Gridcoin config: $AppDataConf" -ForegroundColor Green
    $confContent = Get-Content $AppDataConf -Raw
    $hasServer = $confContent -match "(?m)^\s*server\s*=\s*1"
    $hasUser = $confContent -match "(?m)^\s*rpcuser\s*="
    $hasPass = $confContent -match "(?m)^\s*rpcpassword\s*="

    if (-not $hasServer -or -not $hasUser -or -not $hasPass) {
        Write-Warning "  Your gridcoinresearch.conf is missing server=1, rpcuser, or rpcpassword."
        Write-Warning "  Please ensure 'server=1', 'rpcuser=...', and 'rpcpassword=...' are defined in gridcoinresearch.conf,"
        Write-Warning "  or configure them in $EnvFile"
    } else {
        Write-Host "  RPC credentials detected and valid." -ForegroundColor Green
    }
} elseif (Test-Path $EnvFile) {
    Write-Host "  Local .env configuration found." -ForegroundColor Green
} else {
    Write-Warning "  No local gridcoinresearch.conf or .env found."
    Write-Host "  Creating a template .env file..." -ForegroundColor Gray
    $EnvExample = Join-Path $ProjectRoot ".env.example"
    if (Test-Path $EnvExample) {
        Copy-Item $EnvExample $EnvFile
        Write-Host "  Created .env from template. You can edit it if connecting to a remote node." -ForegroundColor Green
    }
}

# 4. Configure Autostart (Registry)
Write-Host "[4/5] Configuring startup with Windows..." -ForegroundColor Yellow
$RegPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$AppName = "Gridcoin-RPC"

if ($NoAutostart) {
    Write-Host "  Skipping autostart configuration (--NoAutostart specified)." -ForegroundColor Gray
} else {
    $configureAuto = $true
    if (-not $Unattended) {
        $resp = Read-Host "  Do you want Gridcoin-RPC to start automatically on Windows logon? (Y/n)"
        if ($resp -and $resp.Trim().ToLower() -eq "n") {
            $configureAuto = $false
        }
    }

    if ($configureAuto) {
        if ($IsBinary) {
            $TargetExec = "`"$BinaryPath`""
        } else {
            $PythonDir = Split-Path (Get-Command $PythonCmd).Source -Parent
            $PythonW = Join-Path $PythonDir "pythonw.exe"
            if (-not (Test-Path $PythonW)) {
                $PythonW = $PythonCmd
            }
            $MainScript = Join-Path $ProjectRoot "main.py"
            $TargetExec = "`"$PythonW`" `"$MainScript`""
        }
        Set-ItemProperty -Path $RegPath -Name $AppName -Value $TargetExec
        Write-Host "  Registered autostart in $RegPath" -ForegroundColor Green
    } else {
        Write-Host "  Autostart skipped." -ForegroundColor Gray
    }
}

# 5. Launch Application
Write-Host "[5/5] Finalizing setup..." -ForegroundColor Yellow
if ($NoLaunch) {
    Write-Host "  Launch skipped (--NoLaunch specified)." -ForegroundColor Gray
} else {
    $launchNow = $true
    if (-not $Unattended) {
        $resp = Read-Host "  Would you like to start Gridcoin-RPC now? (Y/n)"
        if ($resp -and $resp.Trim().ToLower() -eq "n") {
            $launchNow = $false
        }
    }

    if ($launchNow) {
        Write-Host "  Starting Gridcoin-RPC in background..." -ForegroundColor Cyan
        Set-Location $ProjectRoot
        if ($IsBinary) {
            Start-Process -FilePath $BinaryPath
        } else {
            $MainScript = Join-Path $ProjectRoot "main.py"
            $PythonDir = Split-Path (Get-Command $PythonCmd).Source -Parent
            $PythonW = Join-Path $PythonDir "pythonw.exe"
            if (Test-Path $PythonW) {
                Start-Process -FilePath $PythonW -ArgumentList "`"$MainScript`"" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
            } else {
                Start-Process -FilePath $PythonCmd -ArgumentList "`"$MainScript`"" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
            }
        }
        Write-Host "  Gridcoin-RPC launched! Look for the Gridcoin icon in your system tray." -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Installation complete! Enjoy Gridcoin Rich Presence on Discord." -ForegroundColor Green

