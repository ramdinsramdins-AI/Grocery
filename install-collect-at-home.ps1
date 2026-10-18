# Switches on the Windows task that runs collect-at-home.ps1 at 11 am and 5 pm (or as soon as the PC is on after a
# missed time) and collects once straight away; -Remove switches it off. Run it from the project folder in a normal
# PowerShell window:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install-collect-at-home.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install-collect-at-home.ps1 -Remove
# Run it again after changing collect-at-home.ps1 (the task uses a copy in %LOCALAPPDATA%\ShelfCheck), or to start
# collecting again after a store blocked this PC.
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$Name = "Shelf Check - collect NJK prices"
$Base = Join-Path $env:LOCALAPPDATA "ShelfCheck"
$Script = Join-Path $Base "collect-at-home.ps1"
$Log = Join-Path $Base "collect-at-home.log"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Switched off. The log and the task's copy of the project stay in $Base; you can delete that folder."
    return
}

New-Item -ItemType Directory -Force $Base | Out-Null
Copy-Item (Join-Path $PSScriptRoot "collect-at-home.ps1") $Script -Force
Remove-Item (Join-Path $Base "collect-at-home.paused.txt") -ErrorAction SilentlyContinue

# conhost --headless runs PowerShell without flashing a window, but it splits a path at spaces ("C:\Users\Dell 32"),
# so it gets the short 8.3 form of the path. Without one, fall back to a hidden PowerShell window (it may flash).
$short = (New-Object -ComObject Scripting.FileSystemObject).GetFile($Script).ShortPath
if ($short -notmatch " ") {
    $action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File $short"
} else {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`""
}
$times = (New-ScheduledTaskTrigger -Daily -At "11:00"), (New-ScheduledTaskTrigger -Daily -At "17:00")
$who = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$opts = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Name -Force -Action $action -Trigger $times -Principal $who -Settings $opts `
    -Description "Collects NJK prices on this PC (NJK refuses GitHub's servers) and sends them to the Shelf Check GitHub repo. Log: $Log" | Out-Null
Start-ScheduledTask -TaskName $Name
Write-Host "Switched on: '$Name' collects at 11 am and 5 pm (or when the PC is next on). It is collecting once now, which takes about 3 minutes. Log: $Log"
