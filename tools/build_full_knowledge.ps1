# ============================================================
# EverQuestie FULL Knowledge Database Build
# ============================================================
#
# Builds a fresh EverQuestie knowledge database from:
#   - Installed EverQuest client
#   - Local Allakhazam HTTrack mirror
#   - everquest1-mcp inventory + structured rich details
#   - Good's maps
#   - Brewall maps
#   - Repository-approved travel supplements
#
# Then:
#   - Finalizes the immutable knowledge snapshot
#   - Audits MCP inventory + rich details in working and snapshot DBs
#   - Runs route acceptance
#   - Runs the complete regression suite
#   - Emits route/frontier reports and snapshot SHA-256
#
# Normal EverQuestie users do NOT need Node.js, MCP, source mirrors,
# map packs, or a source checkout. Those are builder inputs only.
# ============================================================

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# Project root
# ------------------------------------------------------------

$ProjectRoot = "C:\Everquestie"
Set-Location $ProjectRoot

# ------------------------------------------------------------
# Source paths
# ------------------------------------------------------------

$EqInstall = "C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest"
$AllakhazamMirror = "C:\AllakhazamEverquest\EQ_Allakhazam_DB\everquest.allakhazam.com"
$McpRepo = "C:\Everquestie\third_party\everquest1-mcp"
$GoodsMaps = "C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest\maps\Good's Maps"
$BrewallMaps = "C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest\maps\Brewall"

# ------------------------------------------------------------
# Outputs
# ------------------------------------------------------------

$WorkingDb = Join-Path $ProjectRoot "build\working.sqlite3"
$SnapshotDb = Join-Path $ProjectRoot "dist\everquestie-knowledge.sqlite3"
$RouteReport = Join-Path $ProjectRoot "build\route-acceptance.json"
$FrontierReport = Join-Path $ProjectRoot "build\provider-travel-frontier.json"

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

function Get-NewestFileDate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$SourceName
    )

    if (-not (Test-Path $Path -PathType Container)) {
        throw "$SourceName directory does not exist: $Path"
    }

    $Newest = Get-ChildItem $Path -File -Recurse -ErrorAction Stop |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $Newest) {
        throw "$SourceName directory contains no files: $Path"
    }

    return $Newest.LastWriteTime.ToString("yyyy-MM-dd")
}

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Stage
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$Stage failed with exit code $LASTEXITCODE."
    }
}

# ------------------------------------------------------------
# Preflight
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " EverQuestie Full Knowledge Build Preflight"
Write-Host "============================================"
Write-Host

$RequiredDirectories = [ordered]@{
    "EverQuest installation" = $EqInstall
    "Allakhazam mirror"      = $AllakhazamMirror
    "everquest1-mcp"         = $McpRepo
    "Good's maps"            = $GoodsMaps
    "Brewall maps"           = $BrewallMaps
}

foreach ($Entry in $RequiredDirectories.GetEnumerator()) {
    if (-not (Test-Path $Entry.Value -PathType Container)) {
        throw "Required input missing: $($Entry.Key) -> $($Entry.Value)"
    }

    Write-Host ("OK  {0}" -f $Entry.Key)
    Write-Host ("    {0}" -f $Entry.Value)
}

$McpDist = Join-Path $McpRepo "dist\index.js"
if (-not (Test-Path $McpDist -PathType Leaf)) {
    throw "everquest1-mcp is present but not built: $McpDist"
}

$Node = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $Node) {
    throw "Node.js was not found on PATH. Node is required only for the builder MCP compile."
}

$DetailBridge = Join-Path $ProjectRoot "tools\mcp_local_detail_bridge.mjs"
if (-not (Test-Path $DetailBridge -PathType Leaf)) {
    throw "Required MCP rich-detail compiler is missing: $DetailBridge"
}

Write-Host "OK  Node.js"
Write-Host ("    {0}" -f $Node.Source)
Write-Host "OK  MCP rich-detail compiler"
Write-Host ("    {0}" -f $DetailBridge)

# ------------------------------------------------------------
# Automatic source/build versions
# ------------------------------------------------------------

Write-Host
Write-Host "Determining source versions from local files..."
Write-Host

$BuildDate = Get-Date
$Version = $BuildDate.ToString("yyyy.MM.dd") + "-full"

$AllakhazamVersion = Get-NewestFileDate `
    -Path $AllakhazamMirror `
    -SourceName "Allakhazam mirror"

$GoodsVersion = Get-NewestFileDate `
    -Path $GoodsMaps `
    -SourceName "Good's maps"

$BrewallVersion = Get-NewestFileDate `
    -Path $BrewallMaps `
    -SourceName "Brewall maps"

Write-Host "============================================"
Write-Host " Resolved Build Configuration"
Write-Host "============================================"
Write-Host
Write-Host "Build version:      $Version"
Write-Host "Allakhazam version: $AllakhazamVersion"
Write-Host "Good's version:     $GoodsVersion"
Write-Host "Brewall version:    $BrewallVersion"
Write-Host "Working DB:         $WorkingDb"
Write-Host "Final snapshot:     $SnapshotDb"
Write-Host

New-Item -ItemType Directory -Force -Path (Split-Path $WorkingDb -Parent) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $SnapshotDb -Parent) | Out-Null

# ------------------------------------------------------------
# Full knowledge build
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " Building EverQuestie Knowledge Database"
Write-Host "============================================"
Write-Host

python .\tools\build_knowledge_db.py `
    --working-db $WorkingDb `
    --snapshot-db $SnapshotDb `
    --version $Version `
    --eq-install $EqInstall `
    --allakhazam-mirror $AllakhazamMirror `
    --allakhazam-version $AllakhazamVersion `
    --mcp-repository $McpRepo `
    --map-pack "Goods=$GoodsMaps" `
    --map-version "Goods=$GoodsVersion" `
    --map-pack "Brewall=$BrewallMaps" `
    --map-version "Brewall=$BrewallVersion" `
    --route-report $RouteReport `
    --provider-travel-frontier-report $FrontierReport `
    --require-route-acceptance `
    --force

Assert-LastExitCode "EverQuestie full knowledge build"

# ------------------------------------------------------------
# MCP completeness gate
# ------------------------------------------------------------
#
# A FULL build must contain both the broad MCP identity inventory and the
# structured rich-detail layer. Audit both the mutable builder DB and the
# finalized artifact so finalization cannot accidentally strip the details.
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " Verifying MCP Inventory + Rich Details"
Write-Host "============================================"
Write-Host

Write-Host "Working database:"
python .\tools\audit_mcp_knowledge.py $WorkingDb --require-details
Assert-LastExitCode "Working-DB MCP knowledge audit"

Write-Host
Write-Host "Finalized knowledge snapshot:"
python .\tools\audit_mcp_knowledge.py $SnapshotDb --require-details
Assert-LastExitCode "Snapshot MCP knowledge audit"

# ------------------------------------------------------------
# Final independent route acceptance
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " Final Route Acceptance Verification"
Write-Host "============================================"
Write-Host

python .\tools\audit_route_acceptance.py `
    $SnapshotDb `
    --full-paths `
    --fail-unreachable

Assert-LastExitCode "Finalized knowledge snapshot route acceptance"

# ------------------------------------------------------------
# Complete regression suite
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " Running EverQuestie Regression Suite"
Write-Host "============================================"
Write-Host

python -m unittest discover `
    -s tests `
    -p "test_*.py"

Assert-LastExitCode "EverQuestie regression suite"

# ------------------------------------------------------------
# Final artifact information
# ------------------------------------------------------------

$WorkingInfo = Get-Item $WorkingDb
$SnapshotInfo = Get-Item $SnapshotDb

$WorkingMiB = [Math]::Round($WorkingInfo.Length / 1MB, 1)
$SnapshotMiB = [Math]::Round($SnapshotInfo.Length / 1MB, 1)
$SnapshotHash = (Get-FileHash -Algorithm SHA256 $SnapshotDb).Hash.ToLowerInvariant()

Write-Host
Write-Host "============================================"
Write-Host " EVERQUESTIE FULL KNOWLEDGE BUILD COMPLETE"
Write-Host "============================================"
Write-Host
Write-Host "Version:"
Write-Host "  $Version"
Write-Host
Write-Host "Source versions:"
Write-Host "  Allakhazam : $AllakhazamVersion"
Write-Host "  Good's     : $GoodsVersion"
Write-Host "  Brewall    : $BrewallVersion"
Write-Host
Write-Host "Working database:"
Write-Host "  $WorkingDb"
Write-Host "  $WorkingMiB MiB"
Write-Host
Write-Host "Immutable knowledge snapshot:"
Write-Host "  $SnapshotDb"
Write-Host "  $SnapshotMiB MiB"
Write-Host
Write-Host "Snapshot SHA-256:"
Write-Host "  $SnapshotHash"
Write-Host
Write-Host "Reports:"
Write-Host "  Route acceptance : $RouteReport"
Write-Host "  Travel frontier  : $FrontierReport"
Write-Host
Write-Host "Build passed:"
Write-Host "  EQ client        : included"
Write-Host "  Allakhazam       : included"
Write-Host "  MCP inventory    : verified"
Write-Host "  MCP rich details : verified"
Write-Host "  Good's maps      : included"
Write-Host "  Brewall maps     : included"
Write-Host "  Travel manifests : automatically compiled"
Write-Host "  Route acceptance : passed"
Write-Host "  Regression tests : passed"
Write-Host
Write-Host "============================================"
