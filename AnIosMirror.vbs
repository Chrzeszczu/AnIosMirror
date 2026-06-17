' AnIosMirror launcher - no console window
Set ws = CreateObject("WScript.Shell")
ws.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetFile(WScript.ScriptFullName).ParentFolder.Path
ws.Run "pythonw main.pyw", 0, False
