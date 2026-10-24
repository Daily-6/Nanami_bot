Option Explicit
Dim fs, shell, repo, runtime, pythonw, script, custom
Set fs = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
repo = fs.GetParentFolderName(WScript.ScriptFullName)
custom = shell.ExpandEnvironmentStrings("%NANAMI_ASTRBOT_ROOT%")
If custom = "%NANAMI_ASTRBOT_ROOT%" Then
    runtime = fs.BuildPath(fs.GetParentFolderName(repo), "AstrBot")
Else
    runtime = custom
End If
pythonw = fs.BuildPath(runtime, ".venv\Scripts\pythonw.exe")
script = fs.BuildPath(repo, "scripts\control_panel.py")
If Not fs.FileExists(pythonw) Then
    MsgBox "AstrBot Python environment not found. Run setup_astrbot.ps1 first.", 16, "Nanami"
    WScript.Quit 1
End If
shell.CurrentDirectory = repo
shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & script & Chr(34), 1, False
