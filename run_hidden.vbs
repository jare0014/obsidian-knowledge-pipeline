Set WshShell = CreateObject("WScript.Shell")
Dim fso, scriptDir, pythonExe, scriptPath
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonExe = scriptDir & "\.venv\Scripts\pythonw.exe"
scriptPath = scriptDir & "\podcast_server.py"

WshShell.CurrentDirectory = scriptDir
WshShell.Run """" & pythonExe & """ """ & scriptPath & """", 0, False

