Set WshShell = CreateObject("WScript.Shell")
Dim fso, scriptDir, pythonExe, scriptPath
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonExe = scriptDir & "\.venv\Scripts\python.exe"
scriptPath = scriptDir & "\podcast_server.py"

WshShell.CurrentDirectory = scriptDir
WshShell.Run """" & pythonExe & """ -u """ & scriptPath & """", 0, False

