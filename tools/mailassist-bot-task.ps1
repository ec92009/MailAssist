param(
    [ValidateSet("InstallLogon", "InstallStartup", "InstallStartupSystem", "Start", "Stop", "Status", "Uninstall")]
    [string]$Action = "Status",
    [string]$TaskName = "MailAssist Bot",
    [ValidateSet("", "mock", "gmail", "outlook")]
    [string]$Provider = "",
    [int]$PollSeconds = 0,
    [int]$BatchSize = 1,
    [int]$Limit = 10,
    [string]$SelectedModel = "",
    [string]$BaseUrl = "",
    [switch]$DryRun,
    [switch]$Force,
    [switch]$RunOnce,
    [switch]$EnsureUvSync,
    [switch]$Highest,
    [System.Management.Automation.PSCredential]$Credential
)

$ErrorActionPreference = "Stop"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host "STOP: $Message" -ForegroundColor Red
    exit 1
}

function Quote-TaskArgument {
    param([string]$Value)
    if ($Value -match '^[A-Za-z0-9_./:\\-]+$') {
        return $Value
    }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Add-NameValueArgument {
    param(
        [System.Collections.Generic.List[string]]$Items,
        [string]$Name,
        [string]$Value
    )
    if ($Value.Trim()) {
        $Items.Add($Name)
        $Items.Add($Value.Trim())
    }
}

function Write-TaskStatus {
    param([string]$Name)
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Task '$Name' is not installed."
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $Name
    Write-Host "Task:        $Name"
    Write-Host "State:       $($task.State)"
    Write-Host "Last run:    $($info.LastRunTime)"
    Write-Host "Last result: $($info.LastTaskResult)"
    Write-Host "Next run:    $($info.NextRunTime)"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceControlDir = Join-Path $repoRoot "data\control"
$serviceStopFlag = Join-Path $serviceControlDir "service-stop.flag"

function Set-ServiceStopFlag {
    New-Item -ItemType Directory -Force -Path $serviceControlDir | Out-Null
    Set-Content -Path $serviceStopFlag -Value "stop requested $(Get-Date -Format o)" -Encoding UTF8
}

function Clear-ServiceStopFlag {
    Remove-Item -LiteralPath $serviceStopFlag -Force -ErrorAction SilentlyContinue
}

$runner = Join-Path $repoRoot "tools\mailassist-bot-runner.ps1"
$hiddenRunner = Join-Path $repoRoot "tools\mailassist-bot-hidden.vbs"
if (-not (Test-Path $runner)) {
    Stop-WithMessage "Runner script not found at $runner."
}
if (-not (Test-Path $hiddenRunner)) {
    Stop-WithMessage "Hidden runner script not found at $hiddenRunner."
}

if ($Action -eq "Status") {
    Write-TaskStatus -Name $TaskName
    exit 0
}

if ($Action -eq "Start") {
    Clear-ServiceStopFlag
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Started task '$TaskName'."
    Write-TaskStatus -Name $TaskName
    exit 0
}

if ($Action -eq "Stop") {
    Set-ServiceStopFlag
    Stop-ScheduledTask -TaskName $TaskName
    Write-Host "Stopped task '$TaskName'."
    Write-TaskStatus -Name $TaskName
    exit 0
}

if ($Action -eq "Uninstall") {
    Set-ServiceStopFlag
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Uninstalled task '$TaskName'."
    exit 0
}

$taskArgs = [System.Collections.Generic.List[string]]::new()
$taskArgs.Add($hiddenRunner)
Add-NameValueArgument -Items $taskArgs -Name "-Provider" -Value $Provider
if ($PollSeconds -gt 0) {
    $taskArgs.Add("-PollSeconds")
    $taskArgs.Add($PollSeconds.ToString())
}
$taskArgs.Add("-BatchSize")
$taskArgs.Add(([Math]::Max(1, $BatchSize)).ToString())
$taskArgs.Add("-Limit")
$taskArgs.Add(([Math]::Max(1, $Limit)).ToString())
Add-NameValueArgument -Items $taskArgs -Name "-SelectedModel" -Value $SelectedModel
Add-NameValueArgument -Items $taskArgs -Name "-BaseUrl" -Value $BaseUrl
if ($DryRun) {
    $taskArgs.Add("-DryRun")
}
if ($Force) {
    $taskArgs.Add("-Force")
}
if ($RunOnce) {
    $taskArgs.Add("-RunOnce")
}
if ($EnsureUvSync) {
    $taskArgs.Add("-EnsureUvSync")
}

$argumentText = ($taskArgs | ForEach-Object { Quote-TaskArgument $_ }) -join " "
$taskAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $argumentText -WorkingDirectory $repoRoot
$runLevel = if ($Highest) { "Highest" } else { "Limited" }
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -Hidden `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Clear-ServiceStopFlag

if ($Action -eq "InstallLogon") {
    $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel $runLevel
    $task = New-ScheduledTask `
        -Action $taskAction `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Runs MailAssist watch-loop after the user signs in. MailAssist creates drafts only; it never sends email."
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Write-Host "Installed logon task '$TaskName' for $userId."
    Write-TaskStatus -Name $TaskName
    exit 0
}

if ($Action -eq "InstallStartup") {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    if ($Credential) {
        $userId = $Credential.UserName
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Password -RunLevel $runLevel
        $task = New-ScheduledTask `
            -Action $taskAction `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description "Runs MailAssist watch-loop at startup. MailAssist creates drafts only; it never sends email."
        Register-ScheduledTask `
            -TaskName $TaskName `
            -InputObject $task `
            -User $userId `
            -Password $Credential.GetNetworkCredential().Password `
            -Force | Out-Null
        Write-Host "Installed startup task '$TaskName' for $userId."
    } else {
        $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType S4U -RunLevel $runLevel
        $task = New-ScheduledTask `
            -Action $taskAction `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description "Runs MailAssist watch-loop at startup without storing a password. MailAssist creates drafts only; it never sends email."
        Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
        Write-Host "Installed passwordless startup task '$TaskName' for $userId."
        Write-Host "If Outlook tokens, local user profile data, or Ollama are unavailable in S4U mode, reinstall with -Credential." -ForegroundColor Yellow
    }
    Write-TaskStatus -Name $TaskName
    exit 0
}

if ($Action -eq "InstallStartupSystem") {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $task = New-ScheduledTask `
        -Action $taskAction `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Runs MailAssist watch-loop as LocalSystem at startup. MailAssist creates drafts only; it never sends email."
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
    Write-Host "Installed LocalSystem startup task '$TaskName'."
    Write-Host "This starts before user logon. Ensure Outlook tokens, .env, the Python environment, and Ollama are available without an interactive desktop." -ForegroundColor Yellow
    Write-TaskStatus -Name $TaskName
    exit 0
}

Stop-WithMessage "Unsupported action '$Action'."
