param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$WorkingDb = "",
    [string]$OutputRoot = "",
    [switch]$OneFile,
    [switch]$SkipTests,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$KnowledgeName = "everquestie-knowledge.sqlite3"
$FinalizeTool = Join-Path $PSScriptRoot "finalize_knowledge_snapshot.py"
$WindowsBuilder = Join-Path $PSScriptRoot "build_windows_exe.ps1"

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

$Version = $Version.Trim()
if ([string]::IsNullOrWhiteSpace($Version)) {
    throw "-Version must not be empty."
}
$VersionSafe = [regex]::Replace($Version, "[^A-Za-z0-9._-]+", "-").Trim("-")
if ([string]::IsNullOrWhiteSpace($VersionSafe)) {
    throw "-Version does not contain any filename-safe characters."
}

if ([string]::IsNullOrWhiteSpace($WorkingDb)) {
    $WorkingDb = Join-Path (Join-Path $HOME ".eqquest") "eqquest.sqlite3"
}
$WorkingDb = [System.IO.Path]::GetFullPath($WorkingDb)
if (-not (Test-Path $WorkingDb -PathType Leaf)) {
    throw "Builder database was not found at '$WorkingDb'. Run/catalog EverQuestie first or pass -WorkingDb."
}

$ResolvedOutputRoot = Resolve-FromProject $OutputRoot "release"
$ReleaseDir = Join-Path $ResolvedOutputRoot $VersionSafe
$StagingRoot = Join-Path (Join-Path $ProjectRoot "build\release") $VersionSafe
$Snapshot = Join-Path $StagingRoot $KnowledgeName

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

$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) {
    throw "The Python launcher 'py' was not found in PATH."
}
if (-not (Test-Path $FinalizeTool -PathType Leaf)) {
    throw "Knowledge finalizer was not found: $FinalizeTool"
}
if (-not (Test-Path $WindowsBuilder -PathType Leaf)) {
    throw "Windows build helper was not found: $WindowsBuilder"
}

Write-Host "=== EverQuestie release $Version ==="
Write-Host "Builder DB: $WorkingDb"
Write-Host "Release output: $ReleaseDir"
Write-Host

Write-Host "[1/4] Finalizing immutable knowledge snapshot..."
& py $FinalizeTool --input $WorkingDb --output $Snapshot --version $Version --force
if ($LASTEXITCODE -ne 0) {
    throw "Knowledge finalization failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $Snapshot -PathType Leaf)) {
    throw "Knowledge finalizer completed without producing '$Snapshot'."
}

if ($SkipTests) {
    Write-Host "[2/4] Regression suite skipped by -SkipTests."
}
else {
    Write-Host "[2/4] Running complete regression suite..."
    Push-Location $ProjectRoot
    try {
        & py -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "Regression suite failed with exit code $LASTEXITCODE. Release packaging aborted."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "[3/4] Building Windows application and attaching knowledge snapshot..."
$BuilderArgs = @(
    "-KnowledgeDb", $Snapshot,
    "-DistPath", $ReleaseDir,
    "-CleanOutput"
)
if ($OneFile) {
    $BuilderArgs += "-OneFile"
}
& $WindowsBuilder @BuilderArgs
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

Write-Host "[4/4] Writing manifest and distributable ZIP..."
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
Write-Host "  user DB:    NOT included; created/preserved separately on each player machine"
