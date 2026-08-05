[CmdletBinding()]
param(
    [string]$LocalInventory = '.\catalog_workspace\parity_records\2026-07-30T15-39-05\LOCAL_FILE_INVENTORY.jsonl',
    [string]$DriveInventory = '.\archive\reconciliation\DRIVE_FILE_INVENTORY_2026-07-30.json',
    [string]$OutputRoot = '.\archive\reconciliation'
)

$ErrorActionPreference = 'Stop'
$timestamp = Get-Date -Format 'yyyy-MM-ddTHH-mm-ss'
$out = Join-Path $OutputRoot $timestamp
if (Test-Path -LiteralPath $out) { throw "Refusing to overwrite existing reconciliation: $out" }
New-Item -ItemType Directory -Path $out | Out-Null

function Get-Key([string]$name, [Int64]$bytes) {
    return ('{0}|{1}' -f $name.ToLowerInvariant(), $bytes)
}

function Get-ProposedLocalPath($drive) {
    $relative = $drive.path -replace '^BG3/', ''
    if ($relative -eq 'CATALOG/BG3 Reference Catalog — B26 — Human Reference.xlsx') { return 'catalog/B26/BG3 Reference Catalog — B26 — Human Reference.xlsx' }
    if ($relative -eq 'CATALOG/BG3 Reference Catalog — B26 — Collection Memberships.csv') { return 'catalog/B26/BG3 Reference Catalog — B26 — Collection Memberships.csv' }
    if ($relative -match '^CATALOG/B26/(.+)$') { return "catalog/B26/$($Matches[1])" }
    if ($relative -match '^SOURCES/COLLECTIONS/(.+)$') { return "data/collections/$($Matches[1])" }
    if ($relative -match '^SOURCES/MODIO/(.+)$') { return "data/modio/$($Matches[1])" }
    if ($relative -match '^SOURCES/NEXUS/(.+)$') { return "data/nexus/$($Matches[1])" }
    if ($relative -match '^SCRAPER/app/(.+)$') { return "app/$($Matches[1])" }
    return "archive/drive_mirror/$relative"
}

$local = @(Get-Content -LiteralPath $LocalInventory | ForEach-Object { $_ | ConvertFrom-Json }) |
    Where-Object { $_.local_path -notlike 'archive/reconciliation/*' }
$driveDocument = Get-Content -Raw -LiteralPath $DriveInventory | ConvertFrom-Json -Depth 20
$drive = @($driveDocument.files)

$localByKey = @{}
foreach ($record in $local) {
    if ($record.action -eq 'exception_requires_user_approval') { continue }
    $key = Get-Key ([IO.Path]::GetFileName($record.local_path)) ([int64]$record.bytes)
    if (-not $localByKey.ContainsKey($key)) { $localByKey[$key] = [System.Collections.Generic.List[object]]::new() }
    $localByKey[$key].Add($record)
}

$pairedLocalPaths = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$rows = foreach ($item in $drive) {
    $key = Get-Key $item.title ([int64]$item.size)
    $candidates = if ($localByKey.ContainsKey($key)) { @($localByKey[$key]) } else { @() }
    $action = if ($candidates.Count -eq 0) { 'copy_drive_to_local' } elseif ($candidates.Count -eq 1) { 'verify_existing_pair' } else { 'conflict_requires_choice' }
    if ($candidates.Count -eq 1) { [void]$pairedLocalPaths.Add($candidates[0].local_path) }
    [pscustomobject][ordered]@{
        record_type = 'drive_file'
        action = $action
        approval_status = if ($action -eq 'conflict_requires_choice') { 'requires_user_choice' } else { 'not_applicable' }
        match_method = if ($candidates.Count -eq 0) { 'none' } elseif ($candidates.Count -eq 1) { 'filename_and_size_candidate; SHA-256 still required' } else { 'ambiguous_filename_and_size_candidate; SHA-256 required' }
        local_path = if ($candidates.Count -eq 1) { $candidates[0].local_path } else { $null }
        proposed_local_path = Get-ProposedLocalPath $item
        candidate_local_paths = ($candidates | ForEach-Object local_path) -join '; '
        bytes = [int64]$item.size
        sha256 = $null
        mime_type = $item.mime_type
        drive_id = $item.id
        drive_path = $item.path
        drive_url = $item.url
        drive_modified_utc = $item.modified_time
        native_source_mime_type = if ($item.mime_type -like 'application/vnd.google-apps.*') { $item.mime_type } else { $null }
        native_revision_id = $null
        local_export_format = if ($item.mime_type -eq 'application/vnd.google-apps.document') { 'docx (required)' } elseif ($item.mime_type -eq 'application/vnd.google-apps.spreadsheet') { 'xlsx (required)' } elseif ($item.mime_type -eq 'application/vnd.google-apps.presentation') { 'pptx (required)' } else { $null }
        reason = if ($action -eq 'copy_drive_to_local') { 'No local filename/size candidate found.' } elseif ($action -eq 'verify_existing_pair') { 'Candidate pair requires byte-level verification before it is accepted.' } else { 'Several local candidates share this filename and size.' }
    }
}

foreach ($item in $local) {
    if ($item.action -eq 'exception_requires_user_approval') {
        $rows += [pscustomobject][ordered]@{
            record_type='local_file'; action='exception_requires_user_approval'; approval_status='approved_default_exception'; match_method='excluded'; local_path=$item.local_path; proposed_local_path=$null; candidate_local_paths=$null; bytes=[int64]$item.bytes; sha256=$item.sha256; mime_type=$item.mime_type; drive_id=$null; drive_path=$null; drive_url=$null; drive_modified_utc=$null; native_source_mime_type=$null; native_revision_id=$null; local_export_format=$null; reason=$item.reason
        }
    } elseif (-not $pairedLocalPaths.Contains($item.local_path)) {
        $rows += [pscustomobject][ordered]@{
            record_type='local_file'; action='copy_local_to_drive'; approval_status='not_applicable'; match_method='no unique Drive filename/size candidate'; local_path=$item.local_path; proposed_local_path=$null; candidate_local_paths=$null; bytes=[int64]$item.bytes; sha256=$item.sha256; mime_type=$item.mime_type; drive_id=$null; drive_path=$null; drive_url=$null; drive_modified_utc=$null; native_source_mime_type=$null; native_revision_id=$null; local_export_format=$null; reason='No unique Drive candidate exists; destination requires Drive-path mapping before upload.'
        }
    }
}

$jsonl = Join-Path $out 'PARITY_APPROVAL_REGISTER.jsonl'
$rows | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 4 } | Set-Content -LiteralPath $jsonl -Encoding utf8NoBOM
$csv = Join-Path $out 'PARITY_APPROVAL_REGISTER.csv'
$rows | Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding utf8NoBOM
$summary = [pscustomobject][ordered]@{
    schema = 'bg3-parity-approval-register/v1'
    generated_utc = (Get-Date).ToUniversalTime().ToString('o')
    local_inventory = (Resolve-Path -LiteralPath $LocalInventory).Path
    drive_inventory = (Resolve-Path -LiteralPath $DriveInventory).Path
    local_source_file_count = $local.Count
    drive_file_count = $drive.Count
    rows = $rows.Count
    action_counts = @($rows | Group-Object action | ForEach-Object { [pscustomobject]@{ action=$_.Name; count=$_.Count; bytes=[int64](($_.Group | Measure-Object bytes -Sum).Sum) } })
    approved_exceptions = @($rows | Where-Object { $_.approval_status -eq 'approved_default_exception' }).Count
    caution = 'Filename/size candidates are not verification. Raw Drive files must be downloaded and SHA-256 compared before a pair is accepted.'
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $out 'RECONCILIATION_SUMMARY.json') -Encoding utf8NoBOM
Write-Output $out
