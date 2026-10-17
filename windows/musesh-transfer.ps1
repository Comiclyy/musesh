# Windows PowerShell 5.1; no installation or administrator access required.
param([string]$Action = "", [string]$PlayerDrive = "", [string]$MusicFolder = "Music")
$ErrorActionPreference = "Stop"
$Inbox = $PSScriptRoot
$ConfigPath = Join-Path $Inbox "windows-settings.json"
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Save-Json($Path, $Value) {
    $temporary = $Path + ".tmp-" + [Guid]::NewGuid().ToString("N")
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 12), $Utf8)
        if (Test-Path -LiteralPath $Path) {
            [IO.File]::Replace($temporary, $Path, $null)
        } else { [IO.File]::Move($temporary, $Path) }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Safe-Path($Root, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or $Relative -match '[\\:\x00-\x1f]' -or
        $Relative.StartsWith('/') -or ($Relative.Split('/') | Where-Object { $_ -in @('', '.', '..') })) {
        throw "Invalid relative music path: $Relative"
    }
    $base = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $full = [IO.Path]::GetFullPath((Join-Path $base $Relative.Replace('/', '\')))
    if (-not $full.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { throw "Path escapes music folder." }
    $check = $full
    while ($check -and $check.Length -ge $base.TrimEnd('\').Length) {
        if (Test-Path -LiteralPath $check) {
            if ((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Linked folders are not supported: $check"
            }
        }
        $check = [IO.Path]::GetDirectoryName($check)
    }
    return $full
}

function Hash($Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Log($Message) {
    Write-Host $Message
    Add-Content -LiteralPath (Join-Path $Inbox "transfer.log") -Value ("{0:o} {1}" -f (Get-Date), $Message)
}

$lock = $null
try {
    $lock = [IO.File]::Open((Join-Path $Inbox "windows.lock"), [IO.FileMode]::OpenOrCreate,
                          [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    if ($Action -eq 'setup') {
        if ($PlayerDrive -notmatch '^[A-Za-z]:[\\]?$') { throw "Usage: musesh-transfer.cmd setup E: [Music]" }
        $drive = $PlayerDrive.Substring(0, 2).ToUpperInvariant()
        if ($drive -eq $env:SystemDrive) { throw "Choose your MP3 player, not the Windows system drive." }
        $volume = @(Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DeviceID -eq $drive })
        if ($volume.Count -ne 1 -or -not $volume[0].VolumeSerialNumber) { throw "Player drive unavailable: $drive" }
        $root = $drive + '\'
        $null = Safe-Path $root $MusicFolder
        $marker = Join-Path $root '.musesh-player.json'
        if (Test-Path -LiteralPath $marker) {
            $token = (Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).token
            if (-not $token) { throw "Invalid existing player marker." }
        } else {
            $token = [Guid]::NewGuid().ToString('N')
        }
        if (Test-Path -LiteralPath $ConfigPath) {
            $previous = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
            if ($previous.token -ne $token) { throw "This handoff folder is configured for another player. Use a separate shared folder." }
        }
        if (-not (Test-Path -LiteralPath $marker)) { Save-Json $marker @{ token = $token; version = 1 } }
        Save-Json $ConfigPath @{ version = 1; serial = $volume[0].VolumeSerialNumber; token = $token; music = $MusicFolder }
        Log "Setup saved for $drive\$MusicFolder. Next time run musesh-transfer.cmd with no arguments."
        exit 0
    }
    if ($Action) { throw "Run musesh-transfer.cmd with no arguments, or use setup E: once." }
    if (-not (Test-Path -LiteralPath $ConfigPath)) { throw "First run: musesh-transfer.cmd setup E: (use your player's drive)." }
    $config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    if ($config.version -ne 1 -or -not $config.token -or -not $config.serial) { throw "Invalid Windows configuration. Run setup again." }
    $players = @()
    foreach ($volume in @(Get-CimInstance Win32_LogicalDisk)) {
        if ($volume.VolumeSerialNumber -ne $config.serial) { continue }
        $marker = Join-Path ($volume.DeviceID + '\') '.musesh-player.json'
        if (Test-Path -LiteralPath $marker) {
            if ((Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).token -eq $config.token) { $players += $volume }
        }
    }
    if ($players.Count -ne 1) { throw "Expected one configured player; found $($players.Count). Connect the player and retry." }
    $playerRoot = $players[0].DeviceID + '\'
    $destination = Safe-Path $playerRoot $config.music
    $receiptRoot = Join-Path $Inbox 'receipts'
    $null = [IO.Directory]::CreateDirectory($receiptRoot)
    $copied = 0; $skipped = 0; $failed = 0
    $free = [long]$players[0].FreeSpace
    $batches = @(Get-ChildItem -LiteralPath (Join-Path $Inbox 'batches') -Directory |
                 Where-Object { -not $_.Name.StartsWith('.') } | Sort-Object Name)
    foreach ($batch in $batches) {
        try {
            $manifest = Get-Content -LiteralPath (Join-Path $batch.FullName 'manifest.json') -Raw | ConvertFrom-Json
        } catch {
            # Mac preparation may retire a fully acknowledged batch after our
            # directory listing. No pending music is ever retired this way.
            if (-not (Test-Path -LiteralPath $batch.FullName)) { continue }
            throw
        }
        if ($manifest.version -ne 1 -or $manifest.batch_id -ne $batch.Name) { throw "Unsupported or invalid batch: $($batch.Name)" }
        foreach ($item in $manifest.files) {
            $marker = Join-Path $playerRoot '.musesh-player.json'
            if (-not (Test-Path -LiteralPath $marker) -or
                (Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).token -ne $config.token) {
                throw "The configured player disconnected. Pending songs are kept; reconnect it and retry."
            }
            $temp = $null
            try {
                if ($item.id -notmatch '^[a-f0-9]{64}$' -or $item.sha256 -notmatch '^[a-f0-9]{64}$' -or
                    $item.size -le 0 -or -not $item.path.EndsWith('.mp3', [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Invalid music manifest entry."
                }
                $receiptPath = Join-Path $receiptRoot ($item.id + '.json')
                if (Test-Path -LiteralPath $receiptPath) {
                    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
                    if ($receipt.player -ne $config.token) { throw "Receipt belongs to another player. Use a separate handoff folder." }
                    $skipped++; continue
                }
                $source = Safe-Path (Join-Path $batch.FullName 'music') $item.path
                $target = Safe-Path $destination $item.path
                if ((Test-Path -LiteralPath $target) -and (Hash $target) -ne $item.sha256) {
                    $relative = $item.path.Substring(0, $item.path.Length - 4) + ' [' + $item.sha256.Substring(0, 12) + '].mp3'
                    $target = Safe-Path $destination $relative
                    if ((Test-Path -LiteralPath $target) -and (Hash $target) -ne $item.sha256) {
                        throw "Conflicting music exists at $target"
                    }
                }
                if (Test-Path -LiteralPath $target) {
                    $skipped++
                } else {
                    if ($free -lt ([long]$item.size + 1048576)) { throw "Not enough free space on the player." }
                    $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
                    $temp = $target + '.musesh-part'
                    [IO.File]::Copy($source, $temp, $true)
                    if ((Get-Item -LiteralPath $temp).Length -ne $item.size -or (Hash $temp) -ne $item.sha256) {
                        throw "Copy verification failed."
                    }
                    [IO.File]::Move($temp, $target)
                    $temp = $null
                    $copied++
                    $free -= [long]$item.size
                }
                Save-Json $receiptPath @{ version = 1; id = $item.id; sha256 = $item.sha256; player = $config.token;
                                          path = $target.Substring($playerRoot.Length); uploaded_at = [DateTime]::UtcNow.ToString('o') }
                Log "Verified: $($item.path)"
            } catch {
                $failed++
                Log "FAILED: $($item.path): $($_.Exception.Message)"
            } finally {
                if ($temp -and (Test-Path -LiteralPath $temp)) { Remove-Item -LiteralPath $temp -Force }
            }
        }
    }
    Log "Finished: $copied copied, $skipped already handled, $failed failed. Failed songs remain pending."
    if ($failed) { exit 1 }
    exit 0
} catch {
    Write-Host "Transfer stopped: $($_.Exception.Message)"
    try { Add-Content -LiteralPath (Join-Path $Inbox 'transfer.log') -Value $_.Exception.Message } catch {}
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
}
