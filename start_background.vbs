Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

cmd = "cmd.exe /c start """" pythonw """ & scriptDir & "\main.py"""
WshShell.Run cmd, 0, False
