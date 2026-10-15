# Switches on the Windows task that runs upload-woolworths.ps1 every 10 minutes (and at log on), or off with -Remove.
# Run it from the project folder in a normal PowerShell window:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install-woolworths-uploader.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install-woolworths-uploader.ps1 -Remove
# Run it again after changing upload-woolworths.ps1, since the task uses a copy in %LOCALAPPDATA%\ShelfCheck.
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$Name = "Shelf Check - upload Woolworths prices"
$Base = Join-Path $env:LOCALAPPDATA "ShelfCheck"
$Script = Join-Path $Base "upload-woolworths.ps1"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Switched off. The log and the uploader's copy of the project stay in $Base; you can delete that folder."
    return
}

New-Item -ItemType Directory -Force $Base | Out-Null
Copy-Item (Join-Path $PSScriptRoot "upload-woolworths.ps1") $Script -Force

# conhost --headless runs PowerShell without flashing a window, but it splits a path at spaces ("C:\Users\Dell 32"),
# so it gets the short 8.3 form of the path. Without one, fall back to a hidden PowerShell window (it may flash).
$short = (New-Object -ComObject Scripting.FileSystemObject).GetFile($Script).ShortPath
if ($short -notmatch " ") {
    $action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File $short"
} else {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`""
}
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$who = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$opts = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Name -Force -Action $action -Trigger $every, $logon -Principal $who -Settings $opts `
    -Description "Sends a new woolworths.json from Downloads to the Shelf Check GitHub repo, then moves old price files to the Recycle Bin. Log: $Base\upload-woolworths.log" | Out-Null
Write-Host "Switched on: '$Name' checks your Downloads folder every 10 minutes. Log: $Base\upload-woolworths.log"
