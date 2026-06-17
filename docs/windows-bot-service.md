# Windows Bot Service

MailAssist already has the long-running bot entrypoint:

```powershell
.\.venv\Scripts\mailassist.exe review-bot --action watch-loop --provider outlook
```

For Windows, the pragmatic service-like host is Task Scheduler. It can run the
existing bot loop after user logon, or at machine startup with credentials. A
native Windows Service wrapper can come later if packaging requires it.

## Before Installing

Run these once from the repo root:

```powershell
uv venv --python 3.12 .venv
uv sync
Copy-Item docs\magali-outlook.env.example .env
```

Then edit `.env` with the real Outlook client id, tenant value, model, and any
polling settings. Complete the no-send checks before enabling the live loop:

```powershell
.\.venv\Scripts\python.exe .\tools\set-outlook-client-id.py
```

```powershell
.\.venv\Scripts\mailassist.exe outlook-setup-check --expected-email <mailbox-email>
.\.venv\Scripts\mailassist.exe ollama-setup-check --model qwen3:8b
```

The setup check stores the Outlook refresh token under ignored local `secrets/`.
Unattended mode cannot complete an interactive device-code sign-in, so that
token must exist before the task starts.

## Run In The Current Window

This starts the bot until the PowerShell window is closed or interrupted:

```powershell
.\tools\mailassist-bot-runner.ps1 -Provider outlook -PollSeconds 60
```

Safer dry-run first pass:

```powershell
.\tools\mailassist-bot-runner.ps1 -Provider outlook -PollSeconds 60 -DryRun
```

Runner stdout/stderr is written to ignored local logs under
`data\service-logs\`. The bot also writes JSONL activity under
`data\bot-logs\`.

## Install A Logon Task

This is the recommended first service-like mode. It starts after the Windows
user signs in, which matches how Ollama for Windows commonly runs during early
testing.

```powershell
.\tools\mailassist-bot-task.ps1 -Action InstallLogon -Provider outlook -PollSeconds 60
.\tools\mailassist-bot-task.ps1 -Action Start
```

## Install A Startup Task

This is the "run whether the user is logged on or not" path. It should be used
only after provider auth and Ollama are both available without interactive UI.

Recommended credential-backed form:

```powershell
$cred = Get-Credential "$env:USERDOMAIN\$env:USERNAME"
.\tools\mailassist-bot-task.ps1 -Action InstallStartup -Provider outlook -PollSeconds 60 -Credential $cred
```

Passwordless S4U form:

```powershell
.\tools\mailassist-bot-task.ps1 -Action InstallStartup -Provider outlook -PollSeconds 60
```

If S4U mode cannot see Outlook tokens, user-profile files, or Ollama models,
reinstall with `-Credential`.

## Manage The Task

```powershell
.\tools\mailassist-bot-task.ps1 -Action Status
.\tools\mailassist-bot-task.ps1 -Action Stop
.\tools\mailassist-bot-task.ps1 -Action Start
.\tools\mailassist-bot-task.ps1 -Action Uninstall
```

MailAssist creates provider drafts only. It does not send email.

## Ollama Caveat

If Ollama is only running as a tray app in the interactive desktop session, the
startup task may begin before Ollama is available. For unattended operation,
configure Ollama itself as a startup task or service, or use the logon task
until the Windows package owns that setup.
