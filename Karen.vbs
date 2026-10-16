' Karen Voice Assistant — Launcher
' Double-click this to start Karen (starts Ollama server + voice assistant).

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run """" & WshShell.CurrentDirectory & "\run_karen.bat""", 1, False

