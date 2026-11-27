Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = appDir

' Find pythonw.exe (Zero Console GUI Python)
pyw = ""
On Error Resume Next
pyExe = shell.Exec("cmd /c where pythonw").StdOut.ReadLine
On Error GoTo 0
If pyExe <> "" And fso.FileExists(pyExe) Then
    pyw = """" & pyExe & """"
Else
    pyw = "pythonw"
End If

shell.Run pyw & " """ & appDir & "\main.py""", 0, False
