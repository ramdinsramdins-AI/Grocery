# Sends a freshly collected woolworths.json from the Downloads folder to GitHub, so the next scheduled scrape uses it.
# Windows Task Scheduler runs a copy of this every 10 minutes (task "Shelf Check - upload Woolworths prices";
# see HANDOVER.md). When there is no new file it does nothing. After a successful upload it moves every
# woolworths*.json in Downloads to the Recycle Bin and shows a message in the corner of the screen.
# It uploads from its own copy of the repo in %LOCALAPPDATA%\ShelfCheck\Grocery, so it never touches other work.
# Log: %LOCALAPPDATA%\ShelfCheck\upload-woolworths.log
#
# Test without sending anything:  powershell -File upload-woolworths.ps1 -DryRun -Downloads <folder>
param(
    [string]$Downloads = "",
    [switch]$DryRun
)

$RepoUrl = "https://github.com/ramdinsramdins-AI/Grocery.git"
$Base = Join-Path $env:LOCALAPPDATA "ShelfCheck"
$Repo = Join-Path $Base "Grocery"
$Log = Join-Path $Base "upload-woolworths.log"
$Git = "C:\Program Files\Git\cmd\git.exe"
$Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$Email = "341151720+ramdinsramdins-AI@users.noreply.github.com"   # GitHub's private address for the repo owner
$MinShare = 0.7            # a new file with fewer than 70% of the products already on GitHub looks cut short
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

function Remove-ToRecycleBin($Files) {
    if ($DryRun) { Write-Log ("(dry run) would recycle: " + (($Files | ForEach-Object Name) -join ", ")); return }
    Add-Type -AssemblyName Microsoft.VisualBasic
    foreach ($f in $Files) {
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($f.FullName, "OnlyErrorDialogs", "SendToRecycleBin")
    }
}

function Invoke-Git {
    $out = & $Git -C $Repo @args 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "git $($args[0]) failed: $($out -join ' ')" }
    $out
}

# start from GitHub's latest version, put the new file in, commit, and push
function Send-PriceFile($File, $Message) {
    Invoke-Git fetch -q --depth 1 origin main | Out-Null
    Invoke-Git reset -q --hard origin/main | Out-Null
    Copy-Item $File (Join-Path $Repo "woolworths.json") -Force
    Invoke-Git add woolworths.json | Out-Null
    Invoke-Git -c "user.name=Shelf Check uploader" -c "user.email=$Email" commit -q -m $Message | Out-Null
    if ($DryRun) {
        Invoke-Git push --dry-run origin HEAD:main | Out-Null
        Invoke-Git reset -q --hard origin/main | Out-Null
    } else {
        Invoke-Git push -q origin HEAD:main | Out-Null
    }
}

# collected_at and product count of a woolworths.json, or $null when it is not one
function Read-PriceFile($Path) {
    if (-not (Test-Path $Path)) { return $null }
    $info = & $Python -I -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(d['collected_at']); print(len(d['products']['items']))" $Path 2>$null
    if ($LASTEXITCODE -ne 0 -or @($info).Count -lt 2) { return $null }
    [pscustomobject]@{ At = [datetimeoffset]::Parse($info[0]); Count = [int]$info[1] }
}

if (-not $Downloads) {
    $Downloads = (New-Object -ComObject Shell.Application).NameSpace("shell:Downloads").Self.Path
}
$all = @(Get-ChildItem -Path $Downloads -Filter "woolworths*.json" -File -ErrorAction SilentlyContinue)
$files = @($all | Where-Object { $_.Name -notlike "*.not-sent.json" } | Sort-Object LastWriteTime -Descending)
if ($files.Count -eq 0) { exit 0 }

try {
    $newest = $files[0]
    $new = Read-PriceFile $newest.FullName
    if (-not $new) {
        Write-Log "$($newest.Name) is not a complete Woolworths price file; left in Downloads"
        Show-Message "Woolworths prices not sent" "$($newest.Name) in Downloads doesn't look like a finished price file. Try the button again."
        Rename-Item $newest.FullName ($newest.Name -replace "\.json$", ".not-sent.json")
        exit 1
    }

    if (-not (Test-Path (Join-Path $Repo ".git"))) {
        Write-Log "making a copy of the repo in $Repo"
        & $Git clone -q --depth 1 $RepoUrl $Repo 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "could not copy the repo from GitHub" }
    }
    Invoke-Git fetch -q --depth 1 origin main | Out-Null
    Invoke-Git reset -q --hard origin/main | Out-Null

    $current = Read-PriceFile (Join-Path $Repo "woolworths.json")
    if ($current -and $new.At -le $current.At) {
        Write-Log "$($newest.Name) (collected $($new.At)) is not newer than the one on GitHub; recycling old files"
        Remove-ToRecycleBin $all
        exit 0
    }
    if ($current -and $new.Count -lt $MinShare * $current.Count) {
        Write-Log "$($newest.Name) has $($new.Count) products, GitHub has $($current.Count); looks cut short, not sent"
        Show-Message "Woolworths prices not sent" "The new file has only $($new.Count) products (last time $($current.Count)). It may have been stopped early. Try the button again."
        Rename-Item $newest.FullName ($newest.Name -replace "\.json$", ".not-sent.json")
        exit 1
    }

    $when = $new.At.ToLocalTime().ToString("d MMM yyyy h:mm tt")
    $message = "Update Woolworths prices (collected $when)"
    try {
        Send-PriceFile $newest.FullName $message
    } catch {
        # the scheduled scrape may have pushed new prices in the meantime: start again from the latest and retry once
        Write-Log "first try failed ($_); trying again"
        Send-PriceFile $newest.FullName $message
    }
    if ($DryRun) {
        Write-Log "(dry run) $($newest.Name): $($new.Count) products, collected $when; GitHub sign-in works, nothing sent"
    } else {
        Write-Log "sent $($newest.Name): $($new.Count) products, collected $when"
    }
    Remove-ToRecycleBin $all
    Show-Message "Woolworths prices sent to GitHub" "$($new.Count) products from $when. Your site uses them at its next update. Old price files went to the Recycle Bin."
} catch {
    Write-Log "failed: $_"
    Show-Message "Woolworths prices not sent yet" "Something went wrong; it will try again in 10 minutes. Details are in $Log"
    exit 1
}
