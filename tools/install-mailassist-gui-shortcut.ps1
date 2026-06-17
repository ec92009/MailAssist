param(
    [string]$Name = "MailAssist",
    [switch]$Desktop,
    [switch]$StartMenu,
    [switch]$All
)

$ErrorActionPreference = "Stop"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host "STOP: $Message" -ForegroundColor Red
    exit 1
}

function New-MailAssistShortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$Icon
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = "$Icon,0"
    $shortcut.Description = "Open the MailAssist desktop control panel."
    $shortcut.Save()
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repoRoot ".venv\Scripts\pythonw.exe"
$icon = Join-Path $repoRoot "assets\brand\mailassist_icon.ico"

if (-not (Test-Path $pythonw)) {
    Stop-WithMessage "Missing $pythonw. Run 'uv venv --python 3.12 .venv' and 'uv sync' first."
}
if (-not (Test-Path $icon)) {
    Stop-WithMessage "Missing icon at $icon."
}

if (-not $Desktop -and -not $StartMenu -and -not $All) {
    $Desktop = $true
    $StartMenu = $true
}
if ($All) {
    $Desktop = $true
    $StartMenu = $true
}

$arguments = "-m mailassist.cli.main desktop-gui"
$created = @()

if ($Desktop) {
    $desktopDir = [Environment]::GetFolderPath("Desktop")
    $desktopPath = Join-Path $desktopDir "$Name.lnk"
    New-MailAssistShortcut `
        -Path $desktopPath `
        -Target $pythonw `
        -Arguments $arguments `
        -WorkingDirectory $repoRoot `
        -Icon $icon
    $created += $desktopPath
}

if ($StartMenu) {
    $programsDir = [Environment]::GetFolderPath("Programs")
    $startMenuPath = Join-Path $programsDir "$Name.lnk"
    New-MailAssistShortcut `
        -Path $startMenuPath `
        -Target $pythonw `
        -Arguments $arguments `
        -WorkingDirectory $repoRoot `
        -Icon $icon
    $created += $startMenuPath
}

Write-Host "Created MailAssist shortcut(s):"
$created | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "To pin it to the taskbar, right-click the MailAssist shortcut and choose 'Pin to taskbar'."
