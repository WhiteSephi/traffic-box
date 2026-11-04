Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir
strPythonw = strDir & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(strPythonw) Then
    WshShell.Run """" & strPythonw & """ -m src.main", 0, False
Else
    WshShell.Run "pythonw -m src.main", 0, False
End If
