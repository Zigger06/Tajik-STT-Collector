param(
    [Parameter(Mandatory = $true)]
    [string]$BackupRoot,

    [string]$DataRoot = $env:TAJIK_COLLECTOR_DATA,

    [switch]$EncryptedDestinationConfirmed
)

$ErrorActionPreference = "Stop"

if (-not $EncryptedDestinationConfirmed) {
    throw "Refusing backup: mount and unlock an encrypted VeraCrypt/BitLocker destination first, then pass -EncryptedDestinationConfirmed."
}

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Join-Path $PSScriptRoot "runtime"
}

$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$BackupRoot = [System.IO.Path]::GetFullPath($BackupRoot)
$dataDrive = [System.IO.Path]::GetPathRoot($DataRoot)
$backupDrive = [System.IO.Path]::GetPathRoot($BackupRoot)

if ([string]::IsNullOrWhiteSpace($dataDrive) -or [string]::IsNullOrWhiteSpace($backupDrive)) {
    throw "DataRoot and BackupRoot must be on mounted volumes."
}

if ($dataDrive -ieq $backupDrive) {
    throw "Refusing backup: BackupRoot must be on a different mounted volume from the live Collector data."
}

$db = Join-Path $DataRoot "collector.db"
$audio = Join-Path $DataRoot "audio"

if (-not (Test-Path -LiteralPath $db -PathType Leaf)) {
    throw "Collector database not found: $db"
}
if (-not (Test-Path -LiteralPath $audio -PathType Container)) {
    throw "Collector audio directory not found: $audio"
}

if (-not (Test-Path -LiteralPath $BackupRoot)) {
    New-Item -ItemType Directory -Path $BackupRoot | Out-Null
}

Write-Host "Encrypted destination manually confirmed: $backupDrive"
Write-Host "Source database: $db"
Write-Host "Source audio: $audio"
Write-Host "Destination: $BackupRoot"
Write-Host "No source files will be deleted or overwritten."

& py -3.12 (Join-Path $PSScriptRoot "tools\backup_collector.py") `
    --db $db `
    --audio $audio `
    --output $BackupRoot `
    --encrypted-destination-confirmed

if ($LASTEXITCODE -ne 0) {
    throw "Backup failed. Originals were not deleted."
}
