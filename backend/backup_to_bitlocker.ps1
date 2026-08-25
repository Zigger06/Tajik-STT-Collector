param(
    [Parameter(Mandatory = $true)]
    [string]$BackupRoot,

    [string]$DataRoot = $env:TAJIK_COLLECTOR_DATA
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Join-Path $PSScriptRoot "runtime"
}

$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)
$BackupRoot = [System.IO.Path]::GetFullPath($BackupRoot)
$backupDrive = [System.IO.Path]::GetPathRoot($BackupRoot)

if ([string]::IsNullOrWhiteSpace($backupDrive)) {
    throw "BackupRoot must be on a mounted drive, for example B:\TajikSTT-Backups"
}

$bitlocker = Get-BitLockerVolume -MountPoint $backupDrive -ErrorAction Stop
if ($bitlocker.ProtectionStatus -ne "On") {
    throw "Refusing backup: BitLocker protection is not On for $backupDrive"
}

if (-not (Test-Path $BackupRoot)) {
    New-Item -ItemType Directory -Path $BackupRoot | Out-Null
}

$db = Join-Path $DataRoot "collector.db"
$audio = Join-Path $DataRoot "audio"

Write-Host "Encrypted destination confirmed: $backupDrive"
Write-Host "Source database: $db"
Write-Host "Source audio: $audio"
Write-Host "No source files will be deleted or overwritten."

& py -3.12 (Join-Path $PSScriptRoot "tools\backup_collector.py") `
    --db $db `
    --audio $audio `
    --output $BackupRoot `
    --encrypted-destination-confirmed

if ($LASTEXITCODE -ne 0) {
    throw "Backup failed. Originals were not deleted."
}
