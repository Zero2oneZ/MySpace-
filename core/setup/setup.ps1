# cc + cc-studio bootstrap for Windows (PowerShell 7+).
#
# NOTE: cc is a bash-first tool. On Windows you'll get best results via:
#   - WSL2 (Ubuntu/Debian) — run the regular setup.sh inside WSL, or
#   - Git for Windows (which ships bash + sh) and run cc through that bash.
#
# This script:
#   1. Verifies python, git, curl
#   2. Creates ~/.cc and CC_STUDIO_HOME (default $HOME\cc-studio)
#   3. Copies cc + lib/* from this checkout
#   4. Builds the Studio venv with streamlit + requests
#   5. Prints recommended ollama model commands
#
# Usage:   pwsh -ExecutionPolicy Bypass -File setup.ps1
#          $env:CC_STUDIO_HOME = 'D:\cc-studio'; pwsh -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

function Say  ($m) { Write-Host "==" -ForegroundColor Cyan -NoNewline; Write-Host " $m" }
function Ok   ($m) { Write-Host "✓ " -ForegroundColor Green -NoNewline; Write-Host " $m" }
function Warn ($m) { Write-Host "!! $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

$CCHome       = if ($env:CC_HOME) { $env:CC_HOME } else { Join-Path $HOME ".cc" }
$CCStudioHome = if ($env:CC_STUDIO_HOME) { $env:CC_STUDIO_HOME } else { Join-Path $HOME "cc-studio" }
$InstallBin   = if ($env:INSTALL_BIN) { $env:INSTALL_BIN } else { Join-Path $HOME ".local\bin" }
$ScriptDir    = $PSScriptRoot
$SrcRoot      = Split-Path $ScriptDir -Parent

# 1. Deps
Say "Checking system dependencies"
foreach ($cmd in @("python", "git", "curl")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Ok $cmd
    } else {
        Warn "missing: $cmd — install via 'winget install <name>'"
        exit 1
    }
}

# Check for bash (Git Bash or WSL)
$BashPath = Get-Command bash -ErrorAction SilentlyContinue
if (-not $BashPath) {
    Warn "bash not found — install Git for Windows or enable WSL. cc requires bash."
    Write-Host "    winget install --id Git.Git" -ForegroundColor Gray
    exit 1
}
Ok "bash at $($BashPath.Source)"

# 2. Dirs
Say "Preparing directories"
foreach ($d in @("lib", "cache", "scripts", "setup")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $CCHome $d) | Out-Null
}
foreach ($d in @("projects", "models", "datasets", "workflows")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $CCStudioHome $d) | Out-Null
}
New-Item -ItemType Directory -Force -Path $InstallBin | Out-Null
Ok $CCHome
Ok $CCStudioHome

# 3. Install cc + libs
Say "Installing cc binary + libraries"
$CCSource = Join-Path $SrcRoot "cc"
if (Test-Path $CCSource) {
    Copy-Item $CCSource (Join-Path $InstallBin "cc") -Force
    Ok "$InstallBin\cc  (run via bash: bash cc ...)"
} else {
    Warn "$CCSource not found — skipping"
}
foreach ($lib in @("db.py", "studio.py", "tui.py")) {
    $src = Join-Path $SrcRoot "lib\$lib"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $CCHome "lib\$lib") -Force
        Ok "$CCHome\lib\$lib"
    }
}

# 4. Studio venv
if (-not $env:SKIP_VENV) {
    Say "Creating Studio Python venv"
    $venv = Join-Path $CCStudioHome ".venv"
    if (-not (Test-Path $venv)) {
        python -m venv $venv
    }
    $pip = Join-Path $venv "Scripts\pip.exe"
    & $pip install --upgrade pip
    & $pip install streamlit requests pyyaml huggingface-hub
    Ok "venv ready: $venv"
} else {
    Warn "SKIP_VENV set — skipping Python deps install"
}

# 5. Ollama hints
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Say "Detected ollama — recommended models for cc tiny + chat fallback:"
    Write-Host "    ollama pull qwen2.5-coder:1.5b" -ForegroundColor Gray
    Write-Host "    ollama pull llama3.2" -ForegroundColor Gray
    Write-Host "    ollama pull kimi-k2.6:cloud" -ForegroundColor Gray
} else {
    Warn "ollama not found — install from https://ollama.com for local models"
}

# 6. PATH note
Write-Host ""
Warn "Make sure $InstallBin is on your PATH and that you launch cc via bash:"
Write-Host "    bash `$HOME\.local\bin\cc studio" -ForegroundColor Gray
Write-Host ""
Ok "All set. On Windows, cc is happiest under WSL2; native bash via Git for Windows works too."
