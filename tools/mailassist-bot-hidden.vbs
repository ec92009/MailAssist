Option Explicit

Dim fso, shell, scriptPath, toolsDir, repoRoot, runner, command, i

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptPath = WScript.ScriptFullName
toolsDir = fso.GetParentFolderName(scriptPath)
repoRoot = fso.GetParentFolderName(toolsDir)
runner = fso.BuildPath(toolsDir, "mailassist-bot-runner.ps1")

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Quote(runner)
For i = 0 To WScript.Arguments.Count - 1
    command = command & " " & Quote(WScript.Arguments(i))
Next

shell.CurrentDirectory = repoRoot
shell.Run command, 0, True
WScript.Quit 0

Function Quote(value)
    Quote = """" & Replace(CStr(value), """", "\""") & """"
End Function
