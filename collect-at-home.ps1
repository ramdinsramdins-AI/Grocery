# Collects prices on this PC for the stores that refuse GitHub's servers (marked "collect_at_home" in config.json: NJK)
# and sends them to GitHub as <store>.json, so the next scheduled scrape uses them. Windows Task Scheduler runs a copy
# of this at 11 am and 5 pm, or as soon as the PC is on after a missed time (task "Shelf Check - collect NJK prices";
# see HANDOVER.md). It runs the newest scraper.py from GitHub in its own copy of the repo in
# %LOCALAPPDATA%\ShelfCheck\Grocery-home, so it never touches other work. It shows a message only when something goes
# wrong. If a store blocks this PC too, collecting pauses until install-collect-at-home.ps1 is run again: it never
# tries to get around a block.
# Log: %LOCALAPPDATA%\ShelfCheck\collect-at-home.log
#
# Test without sending anything:  powershell -File collect-at-home.ps1 -DryRun
param([switch]$DryRun)

$RepoUrl = "https://github.com/ramdinsramdins-AI/Grocery.git"
$Base = Join-Path $env:LOCALAPPDATA "ShelfCheck"
$Repo = Join-Path $Base "Grocery-home"
$Out = Join-Path $Base "collected"
$Log = Join-Path $Base "collect-at-home.log"
$Paused = Join-Path $Base "collect-at-home.paused.txt"
$Git = "C:\Program Files\Git\cmd\git.exe"
$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$Email = "341151720+ramdinsramdins-AI@users.noreply.github.com"   # GitHub's private address for the repo owner
$Label = "NJK"             # the stores marked collect_at_home in config.json, as shown in messages
$Tries = 3; $RetryWait = 60   # GitHub steps: tries in all, and seconds to wait between them
$env:GCM_INTERACTIVE = "never"; $env:GIT_TERMINAL_PROMPT = "0"   # never wait for a sign-in window nobody sees

New-Item -ItemType Directory -Force $Base | Out-Null

function Write-Log($Message) {
    Add-Content -Path $Log -Value ("{0:yyyy-MM-dd HH:mm}  {1}" -f (Get-Date), $Message) -Encoding UTF8
}

function Show-Message($Title, $Text) {
    if ($DryRun) { Write-Log "(message) $Title - $Text"; return }
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $lines = $xml.GetElementsByTagName("text")
        $lines.Item(0).AppendChild($xml.CreateTextNode($Title)) | Out-Null
        $lines.Item(1).AppendChild($xml.CreateTextNode($Text)) | Out-Null
        $app = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
    } catch {
        Write-Log "could not show a message: $_"
    }
}

function Invoke-Git {
    $out = @(& $Git -C $Repo @args 2>&1 | ForEach-Object { "$_" })
    if ($LASTEXITCODE -ne 0) {
        # the exit code tells failures apart even when git prints nothing (as on 2026-10-20 just after the PC woke)
        $said = (@($out | Where-Object { "$_".Trim() }) -join " ").Trim()
        if (-not $said) { $said = "git printed nothing" }
        throw "git $($args[0]) failed with exit code $LASTEXITCODE`: $said"
    }
    $out
}

# Runs a GitHub step and, when it fails, logs the error, waits a minute and tries again ($Tries in all). Right after
# the PC wakes the network is often not back yet; a retry also starts again from GitHub's latest version, in case the
# scheduled scrape pushed new prices in the meantime.
function Invoke-WithRetry($What, [scriptblock]$Step) {
    for ($try = 1; ; $try++) {
        try { & $Step; return }
        catch {
            if ($try -ge $Tries) { throw "$What failed $Tries times; last error: $($_.Exception.Message)" }
            Write-Log "$What failed (try $try of $Tries): $($_.Exception.Message); trying again in $RetryWait seconds"
            Start-Sleep -Seconds $RetryWait
        }
    }
}

# start from GitHub's latest version, put the new files in, commit, and push
function Send-Files($Files, $Message) {
    Invoke-Git fetch -q --depth 1 origin main | Out-Null
    Invoke-Git reset -q --hard origin/main | Out-Null
    foreach ($f in $Files) {
        Copy-Item $f.FullName (Join-Path $Repo $f.Name) -Force
        Invoke-Git add $f.Name | Out-Null
    }
    Invoke-Git -c "user.name=Shelf Check uploader" -c "user.email=$Email" commit -q -m $Message | Out-Null
    if ($DryRun) {
        Invoke-Git push --dry-run origin HEAD:main | Out-Null
        Invoke-Git reset -q --hard origin/main | Out-Null
    } else {
        Invoke-Git push -q origin HEAD:main | Out-Null
    }
}

if (Test-Path $Paused) {
    Write-Log "paused since a store blocked this PC ($((Get-Content $Paused -Raw).Trim())); run install-collect-at-home.ps1 to start again"
    exit 0
}

try {
    if (-not (Test-Path (Join-Path $Repo ".git"))) {
        Write-Log "making a copy of the repo in $Repo"
        & $Git clone -q --depth 1 $RepoUrl $Repo 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "could not copy the repo from GitHub" }
    }
    Invoke-WithRetry "getting the latest version from GitHub" {
        Invoke-Git fetch -q --depth 1 origin main | Out-Null
        Invoke-Git reset -q --hard origin/main | Out-Null   # the newest scraper.py and config.json, and GitHub's <store>.json
    }

    New-Item -ItemType Directory -Force $Out | Out-Null
    Remove-Item (Join-Path $Out "*.json") -ErrorAction SilentlyContinue
    $output = & $Python (Join-Path $Repo "scraper.py") --collect-home $Out 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    $output | Where-Object { $_ -notmatch " page \d+: " } | ForEach-Object { Write-Log "  $_" }   # per-page lines left out

    $blocked = @($output | Where-Object { $_ -match ": blocked \(" })
    if ($blocked.Count -gt 0) {
        Set-Content -Path $Paused -Value ("{0:yyyy-MM-dd HH:mm}  {1}" -f (Get-Date), ($blocked -join "; ")) -Encoding UTF8
        Write-Log "paused: collecting starts again only when install-collect-at-home.ps1 is run"
        Show-Message "$Label prices: blocked" "$Label refused this PC, so collecting is paused. The site keeps the last prices. Details are in $Log"
    }

    $files = @(Get-ChildItem -Path $Out -Filter "*.json" -File -ErrorAction SilentlyContinue)
    if ($files.Count -gt 0) {
        $names = ($files | ForEach-Object Name) -join ", "
        $message = "Update $Label prices (collected $((Get-Date).ToString('d MMM yyyy h:mm tt')) on the home PC)"
        Invoke-WithRetry "sending $names" { Send-Files $files $message }
        if ($DryRun) { Write-Log "(dry run) $names ready; GitHub sign-in works, nothing sent" } else { Write-Log "sent $names" }
    } elseif ($code -eq 0) {
        Write-Log "nothing new to send"
    }
    if ($code -ne 0 -and $blocked.Count -eq 0) {
        Show-Message "$Label prices not collected" "Something went wrong; it tries again at the next scheduled time. Details are in $Log"
        exit 1
    }
} catch {
    Write-Log "failed: $_"
    Show-Message "$Label prices not sent yet" "Something went wrong; it tries again at the next scheduled time. Details are in $Log"
    exit 1
}
