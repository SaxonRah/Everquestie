param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$WorkingDb = "",
    [string]$OutputRoot = "",
    [string]$PythonExe = "",
    [switch]$OneFile,
    [switch]$SkipTests,
    [switch]$SkipRouteAudit,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$KnowledgeName = "everquestie-knowledge.sqlite3"
$StageTool = Join-Path $PSScriptRoot "stage_release_working_db.py"
$FinalizeTool = Join-Path $PSScriptRoot "finalize_knowledge_snapshot.py"
$ReleaseInputAuditTool = Join-Path $PSScriptRoot "audit_release_inputs.py"
$MapCatalogAuditTool = Join-Path $PSScriptRoot "audit_map_catalog.py"
$RouteAuditTool = Join-Path $PSScriptRoot "audit_route_acceptance.py"
$WindowsBuilder = Join-Path $PSScriptRoot "build_windows_exe.ps1"
$ApprovedTravelDir = Join-Path $ProjectRoot "builder-data\travel-supplements"
$ApprovedZoneAliasDir = Join-Path $ProjectRoot "builder-data\zone-aliases"

function Resolve-FromProject([string]$Value, [string]$DefaultValue) {
    $Chosen = $Value
    if ([string]::IsNullOrWhiteSpace($Chosen)) {
        $Chosen = $DefaultValue
    }
    if ([System.IO.Path]::IsPathRooted($Chosen)) {
        return [System.IO.Path]::GetFullPath($Chosen)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $Chosen))
}

function Resolve-Python([string]$Requested) {
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        $Command = Get-Command $Requested -ErrorAction SilentlyContinue
        if (-not $Command) {
            throw "Requested Python interpreter '$Requested' was not found."
        }
        return $Command.Source
    }
    foreach ($Candidate in @("python", "py")) {
        $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }
    throw "No Python interpreter was found in PATH. Pass -PythonExe explicitly."
}

$Version = $Version.Trim()
if ([string]::IsNullOrWhiteSpace($Version)) {
    throw "-Version must not be empty."
}
$VersionSafe = [regex]::Replace($Version, "[^A-Za-z0-9._-]+", "-").Trim("-")
if ([string]::IsNullOrWhiteSpace($VersionSafe)) {
    throw "-Version does not contain any filename-safe characters."
}

if ([string]::IsNullOrWhiteSpace($WorkingDb)) {
    $WorkingDb = Join-Path (Join-Path $ProjectRoot "build") "working.sqlite3"
}
$WorkingDb = [System.IO.Path]::GetFullPath($WorkingDb)
if (-not (Test-Path $WorkingDb -PathType Leaf)) {
    throw "Builder database was not found at '$WorkingDb'. Build/import a working knowledge DB first or pass -WorkingDb."
}

$ResolvedOutputRoot = Resolve-FromProject $OutputRoot "release"
$ReleaseDir = Join-Path $ResolvedOutputRoot $VersionSafe
$StagingRoot = Join-Path (Join-Path $ProjectRoot "build\release") $VersionSafe
$StagedWorkingDb = Join-Path $StagingRoot "working-with-approved-data.sqlite3"
$Snapshot = Join-Path $StagingRoot $KnowledgeName
$MapCatalogAuditReport = Join-Path $StagingRoot "map-catalog-audit.json"

if (Test-Path $ReleaseDir) {
    if (-not $Force) {
        throw "Release output already exists: $ReleaseDir. Pass -Force to replace this version directory."
    }
    Remove-Item -Recurse -Force $ReleaseDir
}
if (Test-Path $StagingRoot) {
    Remove-Item -Recurse -Force $StagingRoot
}
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null

$PythonCommand = Resolve-Python $PythonExe
foreach ($RequiredTool in @($StageTool, $FinalizeTool, $ReleaseInputAuditTool, $MapCatalogAuditTool, $RouteAuditTool, $WindowsBuilder)) {
    if (-not (Test-Path $RequiredTool -PathType Leaf)) {
        throw "Required release helper was not found: $RequiredTool"
    }
}
if (-not (Test-Path $ApprovedTravelDir -PathType Container)) {
    throw "Approved travel supplement directory was not found: $ApprovedTravelDir"
}
if (-not (Test-Path $ApprovedZoneAliasDir -PathType Container)) {
    throw "Approved zone alias directory was not found: $ApprovedZoneAliasDir"
}

Write-Host "=== EverQuestie release $Version ==="
Write-Host "Builder DB: $WorkingDb"
Write-Host "Release output: $ReleaseDir"
Write-Host "Python interpreter: $PythonCommand"
Write-Host

Write-Host "[1/8] Staging builder DB and compiling approved zone aliases + travel supplements..."
& $PythonCommand $StageTool `
    --input $WorkingDb `
    --output $StagedWorkingDb `
    --supplement-dir $ApprovedTravelDir `
    --zone-alias-dir $ApprovedZoneAliasDir `
    --force
if ($LASTEXITCODE -ne 0) {
    throw "Release staging failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $StagedWorkingDb -PathType Leaf)) {
    throw "Release staging completed without producing '$StagedWorkingDb'."
}

Write-Host "[2/8] Finalizing immutable knowledge snapshot..."
& $PythonCommand $FinalizeTool --input $StagedWorkingDb --output $Snapshot --version $Version --force
if ($LASTEXITCODE -ne 0) {
    throw "Knowledge finalization failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $Snapshot -PathType Leaf)) {
    throw "Knowledge finalizer completed without producing '$Snapshot'."
}

Write-Host "[3/8] Verifying reviewed release inputs against finalized evidence..."
& $PythonCommand $ReleaseInputAuditTool $Snapshot --require-release-inputs
if ($LASTEXITCODE -ne 0) {
    throw "Reviewed release-input audit failed with exit code $LASTEXITCODE. Release packaging aborted."
}

Write-Host "[4/8] Auditing prebuilt shipped map catalog..."
& $PythonCommand $MapCatalogAuditTool $Snapshot `
    --require-source Goods `
    --require-source Brewall `
    --require-versioned-sources `
    --output $MapCatalogAuditReport
if ($LASTEXITCODE -ne 0) {
    throw "Map catalog audit failed with exit code $LASTEXITCODE. Release packaging aborted."
}

if ($SkipRouteAudit) {
    Write-Host "[5/8] Route acceptance gate skipped by -SkipRouteAudit."
}
else {
    Write-Host "[5/8] Verifying canonical route acceptance..."
    & $PythonCommand $RouteAuditTool $Snapshot --full-paths --fail-unreachable
    if ($LASTEXITCODE -ne 0) {
        throw "Route acceptance failed with exit code $LASTEXITCODE. Release packaging aborted."
    }
}

if ($SkipTests) {
    Write-Host "[6/8] Regression suite skipped by -SkipTests."
}
else {
    Write-Host "[6/8] Running complete regression suite..."
    Push-Location $ProjectRoot
    try {
        & $PythonCommand -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "Regression suite failed with exit code $LASTEXITCODE. Release packaging aborted."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "[7/8] Building Windows application and attaching knowledge snapshot..."
$BuilderParams = @{
    KnowledgeDb = $Snapshot
    DistPath = $ReleaseDir
    PythonExe = $PythonCommand
    CleanOutput = $true
}
if ($OneFile) {
    $BuilderParams["OneFile"] = $true
}
& $WindowsBuilder @BuilderParams
if ($LASTEXITCODE -ne 0) {
    throw "Windows application build failed with exit code $LASTEXITCODE."
}

$Target = if ($OneFile) {
    Join-Path $ReleaseDir "EverQuestie.exe"
}
else {
    Join-Path $ReleaseDir "EverQuestie"
}
$Executable = if ($OneFile) {
    $Target
}
else {
    Join-Path $Target "EverQuestie.exe"
}
if (-not (Test-Path $Executable -PathType Leaf)) {
    throw "Release executable is missing: $Executable"
}
if (-not $OneFile) {
    $PackagedKnowledge = Join-Path $Target $KnowledgeName
    if (-not (Test-Path $PackagedKnowledge -PathType Leaf)) {
        throw "Release knowledge snapshot is missing beside the executable: $PackagedKnowledge"
    }
}

Write-Host "[8/8] Writing manifest and distributable ZIP..."
$SnapshotHash = (Get-FileHash -Algorithm SHA256 $Snapshot).Hash.ToLowerInvariant()
$ExecutableHash = (Get-FileHash -Algorithm SHA256 $Executable).Hash.ToLowerInvariant()
$SnapshotBytes = (Get-Item $Snapshot).Length
$ExecutableBytes = (Get-Item $Executable).Length
$BuiltAt = (Get-Date).ToUniversalTime().ToString("o")
$Layout = if ($OneFile) { "one-file" } else { "one-folder" }
$ExecutableRelative = if ($OneFile) { "EverQuestie.exe" } else { "EverQuestie/EverQuestie.exe" }
$KnowledgeRelative = if ($OneFile) { "embedded:$KnowledgeName" } else { "EverQuestie/$KnowledgeName" }

$Manifest = [ordered]@{
    product = "EverQuestie"
    release_version = $Version
    built_at_utc = $BuiltAt
    layout = $Layout
    executable = [ordered]@{
        path = $ExecutableRelative
        sha256 = $ExecutableHash
        bytes = $ExecutableBytes
    }
    knowledge = [ordered]@{
        path = $KnowledgeRelative
        filename = $KnowledgeName
        snapshot_version = $Version
        sha256 = $SnapshotHash
        bytes = $SnapshotBytes
        embedded = [bool]$OneFile
        immutable_runtime = $true
        map_catalog_verified = $true
        map_catalog_sources = @("Goods", "Brewall")
        approved_zone_aliases_compiled = $true
        approved_travel_supplements_compiled = $true
        reviewed_release_inputs_verified = $true
        route_acceptance_verified = [bool](-not $SkipRouteAudit)
    }
    user_state_included = $false
    builder_database_included = $false
}

$ManifestPath = if ($OneFile) {
    Join-Path $ReleaseDir "release-manifest.json"
}
else {
    Join-Path $Target "release-manifest.json"
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $ManifestPath

$Archive = Join-Path $ReleaseDir ("EverQuestie-{0}-windows.zip" -f $VersionSafe)
if (Test-Path $Archive) {
    Remove-Item -Force $Archive
}
if ($OneFile) {
    Compress-Archive -Path @($Executable, $ManifestPath) -DestinationPath $Archive -Force
}
else {
    Compress-Archive -Path $Target -DestinationPath $Archive -Force
}

Write-Host
Write-Host "Release ready."
Write-Host "  executable: $Executable"
if (-not $OneFile) {
    Write-Host "  knowledge:  $(Join-Path $Target $KnowledgeName)"
}
else {
    Write-Host "  knowledge:  embedded immutable snapshot"
}
Write-Host "  manifest:   $ManifestPath"
Write-Host "  archive:    $Archive"
Write-Host "  source DB:  NOT modified; release staging used SQLite backup + approved identity/travel supplements"
Write-Host "  user DB:    NOT included; created/preserved separately on each player machine"
