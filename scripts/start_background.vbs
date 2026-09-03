Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)
WshShell.CurrentDirectory = projectDir

cmd = "cmd.exe /c start """" pythonw """ & projectDir & "\main.py"""
WshShell.Run cmd, 0, False

