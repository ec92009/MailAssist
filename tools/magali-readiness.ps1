param(
    [string]$ExpectedEmail = "MagaliDomingue@goldenyearstaxstrategy.com",
    [string]$Model = "qwen3:8b",
    [string]$ClientId = "",
    [string]$TenantId = "organizations",
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host "STOP: $Message" -ForegroundColor Red
    exit 1
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Stop-WithMessage "Required command not found: $Name"
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "MailAssist Magali readiness check"
Write-Host "This runs read-only Outlook setup plus a MailAssist-path Ollama check."
Write-Host "It does not create drafts or send email."
Write-Host ""

if (-not (Test-Path ".env")) {
    if (-not (Test-Path "docs\magali-outlook.env.example")) {
        Stop-WithMessage "Missing docs\magali-outlook.env.example"
    }
    Copy-Item "docs\magali-outlook.env.example" ".env"
    Write-Host "Created .env from docs\magali-outlook.env.example"
}

$envText = Get-Content ".env" -Raw
if ($ClientId.Trim()) {
    $clientLine = "MAILASSIST_OUTLOOK_CLIENT_ID=$($ClientId.Trim())"
    if ($envText -match "(?m)^MAILASSIST_OUTLOOK_CLIENT_ID=.*$") {
        $envText = $envText -replace "(?m)^MAILASSIST_OUTLOOK_CLIENT_ID=.*$", $clientLine
    } else {
        $envText = $envText.TrimEnd() + "`r`n$clientLine`r`n"
    }
    Set-Content ".env" $envText -Encoding UTF8
    Write-Host "Updated MAILASSIST_OUTLOOK_CLIENT_ID in .env"
}

$envText = Get-Content ".env" -Raw
if ($TenantId.Trim()) {
    $tenantLine = "MAILASSIST_OUTLOOK_TENANT_ID=$($TenantId.Trim())"
    if ($envText -match "(?m)^MAILASSIST_OUTLOOK_TENANT_ID=.*$") {
        $envText = $envText -replace "(?m)^MAILASSIST_OUTLOOK_TENANT_ID=.*$", $tenantLine
    } else {
        $envText = $envText.TrimEnd() + "`r`n$tenantLine`r`n"
    }
    Set-Content ".env" $envText -Encoding UTF8
}

$envText = Get-Content ".env" -Raw
if ($envText -match "<mailassist-entra-application-client-id>") {
    Stop-WithMessage "Paste the work/school Entra Application (client) ID into .env before running this script."
}
$configuredClientId = [regex]::Match($envText, "(?m)^MAILASSIST_OUTLOOK_CLIENT_ID\s*=\s*(.+?)\s*$").Groups[1].Value.Trim()
if ($configuredClientId -notmatch "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$") {
    Write-Host "Warning: MAILASSIST_OUTLOOK_CLIENT_ID does not look like a GUID. Continuing anyway." -ForegroundColor Yellow
}
$configuredTenantId = [regex]::Match($envText, "(?m)^MAILASSIST_OUTLOOK_TENANT_ID\s*=\s*(.+?)\s*$").Groups[1].Value.Trim()
if ($configuredTenantId -match "^(consumers|common)$") {
    Stop-WithMessage "MAILASSIST_OUTLOOK_TENANT_ID is set to $configuredTenantId. Use organizations or the Golden Years tenant id."
}

Require-Command "uv"

if (-not $SkipSync) {
    Write-Host "Syncing Python environment..."
    uv sync
}

$mailassist = Join-Path $repoRoot ".venv\Scripts\mailassist.exe"
if (-not (Test-Path $mailassist)) {
    Stop-WithMessage "MailAssist executable not found at $mailassist. Did uv sync finish?"
}

Write-Host ""
Write-Host "Step 1: Outlook setup check"
Write-Host "Expected mailbox: $ExpectedEmail"
& $mailassist outlook-setup-check --expected-email $ExpectedEmail
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Outlook setup check failed. Do not create drafts."
}

Write-Host ""
Write-Host "Step 2: Ollama setup check"
Write-Host "Model: $Model"
& $mailassist ollama-setup-check --model $Model
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage "Ollama setup check failed. Do not create drafts."
}

Write-Host ""
Write-Host "Readiness checks passed." -ForegroundColor Green
Write-Host "No drafts were created and no email was sent."
