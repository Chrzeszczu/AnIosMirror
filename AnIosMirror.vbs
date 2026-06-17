' AnIosMirror launcher - no console window
Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
vbsDir = fso.GetFile(WScript.ScriptFullName).ParentFolder.Path
ws.CurrentDirectory = vbsDir
On Error Resume Next
ws.Run "cmd /c pythonw main.pyw", 0, False
If Err.Number <> 0 Then
    Set logFile = fso.CreateTextFile(vbsDir & "\launch_error.log", True)
    logFile.WriteLine Now & " - Error: " & Err.Description
    logFile.Close
End If
