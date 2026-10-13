param(
    [switch]$Download
)
$ErrorActionPreference = 'Stop'
$taskLab = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPackage = $(if (Test-Path -LiteralPath (Join-Path $taskLab 'package/app')) { Join-Path $taskLab 'package' } else { $taskLab })
$taskLockPath = Join-Path $taskPackage 'components/DEPENDENCIES_LOCK.json'
$taskLock = Get-Content -LiteralPath $taskLockPath -Raw | ConvertFrom-Json
$taskDownloadRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'downloads/source-001'))
if (-not $taskDownloadRoot.StartsWith($taskLab + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'DOWNLOAD_PATH_OUTSIDE_LAB'
}
if (-not $Download) {
    throw 'DOWNLOAD_NOT_ENABLED: use -Download only after explicit authorization for the fixed official source set.'
}
if ($taskLock.components.Count -ne 5) { throw 'FIXED_COMPONENT_COUNT_CHANGED' }
if (-not (Test-Path -LiteralPath $taskDownloadRoot)) {
    New-Item -ItemType Directory -Path $taskDownloadRoot | Out-Null
}
$taskReceipts = @()
foreach ($taskComponent in $taskLock.components) {
    $taskUri = [Uri]$taskComponent.url
    if ($taskUri.Scheme -ne 'https' -or $taskUri.Host -notin @('www.python.org', 'files.pythonhosted.org')) {
        throw 'NONOFFICIAL_ARCHIVE_URL'
    }
    if ([IO.Path]::GetFileName($taskComponent.filename) -cne $taskComponent.filename) { throw 'INVALID_FILENAME' }
    $taskTarget = Join-Path $taskDownloadRoot $taskComponent.filename
    if (-not (Test-Path -LiteralPath $taskTarget)) {
        $taskTemporary = $taskTarget + '.partial'
        if (Test-Path -LiteralPath $taskTemporary) { throw 'PARTIAL_DOWNLOAD_ALREADY_EXISTS' }
        Invoke-WebRequest -UseBasicParsing -Uri $taskComponent.url -OutFile $taskTemporary
        $taskFile = Get-Item -LiteralPath $taskTemporary
        $taskHash = (Get-FileHash -LiteralPath $taskTemporary -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($taskFile.Length -ne $taskComponent.bytes -or $taskHash -cne $taskComponent.sha256) {
            throw ('DOWNLOADED_ARCHIVE_MISMATCH: ' + $taskComponent.filename + '; rejected bytes retained as .partial')
        }
        Move-Item -LiteralPath $taskTemporary -Destination $taskTarget
    }
    $taskActual = Get-Item -LiteralPath $taskTarget
    $taskActualHash = (Get-FileHash -LiteralPath $taskTarget -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($taskActual.Length -ne $taskComponent.bytes -or $taskActualHash -cne $taskComponent.sha256) {
        throw ('EXISTING_ARCHIVE_MISMATCH: ' + $taskComponent.filename)
    }
    $taskReceipts += [pscustomobject]@{
        filename = $taskComponent.filename
        source_url = $taskComponent.url
        bytes = $taskActual.Length
        sha256 = $taskActualHash
        status = 'SIZE_AND_SHA256_VERIFIED'
    }
}
$taskAncillary = @(
    @{filename='python-3.13.16-embed-amd64.zip.spdx.json';url='https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip.spdx.json'},
    @{filename='python-3.13.16-embed-amd64.zip.sigstore';url='https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip.sigstore'},
    @{filename='latex2mathml-3.81.0-LICENSE';url='https://raw.githubusercontent.com/roniemartinez/latex2mathml/3.81.0/LICENSE';bytes=1071;sha256='4ac1e1da07f6b343d54191c5e1716840534e08591b3f9eaec90d6800cdc47543'}
)
foreach ($taskItem in $taskAncillary) {
    $taskPath = Join-Path $taskDownloadRoot $taskItem.filename
    if (-not (Test-Path -LiteralPath $taskPath)) {
        $taskPartial = $taskPath + '.partial'
        if (Test-Path -LiteralPath $taskPartial) { throw 'PARTIAL_METADATA_ALREADY_EXISTS' }
        Invoke-WebRequest -UseBasicParsing -Uri $taskItem.url -OutFile $taskPartial
        if ($taskItem.sha256) {
            if ((Get-Item -LiteralPath $taskPartial).Length -ne $taskItem.bytes -or
                (Get-FileHash -LiteralPath $taskPartial -Algorithm SHA256).Hash.ToLowerInvariant() -cne $taskItem.sha256) {
                throw ('LICENSE_TEXT_MISMATCH: ' + $taskItem.filename)
            }
        }
        Move-Item -LiteralPath $taskPartial -Destination $taskPath
    }
    $taskReceipts += [pscustomobject]@{
        filename=$taskItem.filename;source_url=$taskItem.url
        bytes=(Get-Item -LiteralPath $taskPath).Length
        sha256=(Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()
        status= $(if($taskItem.sha256){'FIXED_LICENSE_SHA256_VERIFIED'}else{'OFFICIAL_HTTPS_METADATA_CAPTURED_SIGNATURE_VERIFICATION_NOT_RUN'})
    }
}
$taskReceiptPath = Join-Path $taskDownloadRoot 'ACQUISITION_RECEIPT.json'
if (Test-Path -LiteralPath $taskReceiptPath) { throw 'ACQUISITION_RECEIPT_ALREADY_EXISTS' }
$taskDocument = [ordered]@{
    schema='release.runtime_acquisition.v1'
    authorization='Explicit user approval relayed by parent for these five fixed official archives and corresponding license metadata'
    captured_utc=[DateTime]::UtcNow.ToString('o')
    lock_sha256=(Get-FileHash -LiteralPath $taskLockPath -Algorithm SHA256).Hash.ToLowerInvariant()
    files=$taskReceipts
    signature_cryptographic_verification='NOT_RUN'
    no_installers=$true;no_pip=$true;no_global_installation=$true;no_local_content_sent=$true
}
[IO.File]::WriteAllText($taskReceiptPath, ($taskDocument | ConvertTo-Json -Depth 8) + "`n", [Text.UTF8Encoding]::new($false))
$taskReceipts | Select-Object filename,bytes,status | Format-Table -AutoSize
Write-Output ('Acquisition receipt: ' + $taskReceiptPath)
