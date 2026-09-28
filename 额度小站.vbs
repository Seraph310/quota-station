Option Explicit

Dim shell, files, appRoot, pythonPath, appPath, commandLine
Set files = CreateObject("Scripting.FileSystemObject")
appRoot = files.GetParentFolderName(WScript.ScriptFullName)
pythonPath = files.BuildPath(appRoot, ".venv\Scripts\pythonw.exe")
appPath = files.BuildPath(appRoot, "app.py")
commandLine = Quote(pythonPath) & " " & Quote(appPath)

' Syntax/path verification only: no app launch and no dependency installation.
If WScript.Arguments.Named.Exists("check") Then
    WScript.Echo commandLine
    WScript.Quit 0
End If

If Not files.FileExists(pythonPath) Or Not files.FileExists(appPath) Then
    MsgBox "Run install.ps1 in this project folder before starting Quota Station.", vbExclamation, "Quota Station"
    WScript.Quit 1
End If

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = appRoot
shell.Run commandLine, 1, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
