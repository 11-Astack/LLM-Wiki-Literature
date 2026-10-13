param([switch]$Download)
$ErrorActionPreference='Stop'
if(-not $Download) { throw 'DOWNLOAD_NOT_ENABLED' }
$taskLab=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskTarget=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'downloads/source-001'))
if(-not $taskTarget.StartsWith($taskLab+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'DOWNLOAD_PATH_OUTSIDE_LAB' }
$taskItems=@(
    @{filename='CPython-3.13.16-license.rst';url='https://raw.githubusercontent.com/python/cpython/v3.13.16/Doc/license.rst';bytes=58181;sha256='952ac05720d7f1dcb63589b35eb0931b1442eb250230a4ad31198eddf0ad6abc'},
    @{filename='OpenSSL-3.5.9-LICENSE.txt';url='https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.9/LICENSE.txt';bytes=10175;sha256='7d5450cb2d142651b8afa315b5f238efc805dad827d91ba367d8516bc9d49e7a'},
    @{filename='libb2-0.98.1-COPYING';url='https://raw.githubusercontent.com/BLAKE2/libb2/v0.98.1/COPYING';bytes=6556;sha256='6a1ee543e5282cd9061881edf462e6fdab181f328da71fc2c9a6950a80e94d01'},
    @{filename='SQLite-3.50.4-LICENSE.md';url='https://raw.githubusercontent.com/sqlite/sqlite/version-3.50.4/LICENSE.md';bytes=3864;sha256='a7a58d6022c090c528e3167026167b3141d682efc6a3c188b473ba59f1788fc7'},
    @{filename='xz-5.2.5-COPYING';url='https://raw.githubusercontent.com/tukaani-project/xz/v5.2.5/COPYING';bytes=2775;sha256='bcb02973ef6e87ea73d331b3a80df7748407f17efdb784b61b47e0e610d3bb5c'}
)
$taskEntries=@()
foreach($taskItem in $taskItems) {
    $taskPath=Join-Path $taskTarget $taskItem.filename
    if(-not(Test-Path -LiteralPath $taskPath)) {
        $taskPartial=$taskPath+'.partial'
        if(Test-Path -LiteralPath $taskPartial) { throw 'PARTIAL_LICENSE_ALREADY_EXISTS' }
        Invoke-WebRequest -UseBasicParsing -Uri $taskItem.url -OutFile $taskPartial
        if((Get-Item -LiteralPath $taskPartial).Length -ne $taskItem.bytes -or
            (Get-FileHash -LiteralPath $taskPartial -Algorithm SHA256).Hash.ToLowerInvariant() -cne $taskItem.sha256) { throw 'OFFICIAL_LICENSE_TEXT_CHANGED' }
        Move-Item -LiteralPath $taskPartial -Destination $taskPath
    }
    if((Get-Item -LiteralPath $taskPath).Length -ne $taskItem.bytes -or
        (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $taskItem.sha256) { throw 'LOCAL_LICENSE_TEXT_CHANGED' }
    $taskEntries += [pscustomobject]@{filename=$taskItem.filename;source_url=$taskItem.url;bytes=$taskItem.bytes;sha256=$taskItem.sha256;transform='NONE'}
}
$taskHaclUrl='https://raw.githubusercontent.com/python/cpython/v3.13.16/Modules/_hacl/Hacl_Hash_SHA2.c'
$taskHaclSource=Invoke-WebRequest -UseBasicParsing -Uri $taskHaclUrl
$taskHaclBytes=[Text.Encoding]::UTF8.GetBytes($taskHaclSource.Content)
if($taskHaclBytes.Length -ne 36131 -or
    [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskHaclBytes)).ToLowerInvariant() -cne '30638efb75c8b185bb09c3df6977e3f3c5d21a1e696218cf7ade6bc4d5201b31') { throw 'HACL_LICENSE_SOURCE_CHANGED' }
$taskHeaderMatch=[regex]::Match($taskHaclSource.Content,'(?s)\A/\* MIT License.*?\*/')
if(-not $taskHeaderMatch.Success) { throw 'HACL_LICENSE_HEADER_MISSING' }
$taskHeaderBytes=[Text.Encoding]::UTF8.GetBytes($taskHeaderMatch.Value+"`n")
$taskHeaderPath=Join-Path $taskTarget 'HACL-CPython-3.13.16-MIT-header.txt'
if(Test-Path -LiteralPath $taskHeaderPath) { throw 'HACL_LICENSE_OUTPUT_ALREADY_EXISTS' }
[IO.File]::WriteAllBytes($taskHeaderPath,$taskHeaderBytes)
$taskEntries += [pscustomobject]@{filename='HACL-CPython-3.13.16-MIT-header.txt';source_url=$taskHaclUrl;source_bytes=36131;source_sha256='30638efb75c8b185bb09c3df6977e3f3c5d21a1e696218cf7ade6bc4d5201b31';bytes=$taskHeaderBytes.Length;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskHeaderBytes)).ToLowerInvariant();transform='Retained the full original leading MIT copyright/license comment; no executable source saved'}
$taskReceipt=Join-Path $taskTarget 'LICENSE_ACQUISITION_RECEIPT.json'
if(Test-Path -LiteralPath $taskReceipt) { throw 'LICENSE_RECEIPT_ALREADY_EXISTS' }
[IO.File]::WriteAllText($taskReceipt,([ordered]@{schema='release.corresponding_license_acquisition.v1';captured_utc=[DateTime]::UtcNow.ToString('o');files=$taskEntries;no_new_runtime_components=$true;signature_verification='NOT_RUN'} | ConvertTo-Json -Depth 6)+"`n",[Text.UTF8Encoding]::new($false))
$taskEntries | Select-Object filename,bytes,sha256 | Format-Table -AutoSize
