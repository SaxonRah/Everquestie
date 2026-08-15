# ============================================================
# EverQuestie FULL Knowledge Database Build
# ============================================================
#
# Builds a fresh EverQuestie knowledge database from:
#
#   - Installed EverQuest client
#   - Local Allakhazam HTTrack mirror
#   - everquest1-mcp full inventory/details
#   - Good's maps
#   - Brewall maps
#   - Repository-approved travel supplements
#
# Then:
#
#   - Finalizes the immutable knowledge snapshot
#   - Runs route acceptance
#   - Requires all acceptance routes to pass
#   - Writes route/frontier diagnostic reports
#
# Normal EverQuestie users do NOT need these source inputs.
# They receive only the finalized knowledge snapshot.
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

# Installed EverQuest
$EqInstall = "C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest"

# Local HTTrack Allakhazam mirror
$AllakhazamMirror = "C:\AllakhazamEverquest\EQ_Allakhazam_DB\everquest.allakhazam.com"

# Builder-only everquest1-mcp checkout
$McpRepo = "C:\Everquestie\third_party\everquest1-mcp"

# Good's maps
$GoodsMaps = "C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest\maps\Good's Maps"

# Brewall maps
$BrewallMaps = "C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest\maps\Brewall"


# ------------------------------------------------------------
# Output paths
# ------------------------------------------------------------

$WorkingDb = Join-Path $ProjectRoot "build\working.sqlite3"

$SnapshotDb = Join-Path $ProjectRoot "dist\everquestie-knowledge.sqlite3"

$RouteReport = Join-Path $ProjectRoot "build\route-acceptance.json"

$FrontierReport = Join-Path $ProjectRoot "build\provider-travel-frontier.json"


# ------------------------------------------------------------
# Helper: newest file timestamp
# ------------------------------------------------------------
#
# Returns yyyy-MM-dd using the newest LastWriteTime found anywhere
# below the supplied directory.
#
# This avoids manually maintaining source provenance dates.
#

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

    $Newest = $null

    Get-ChildItem $Path -File -Recurse -ErrorAction Stop | ForEach-Object {

        if (($null -eq $Newest) -or ($_.LastWriteTime -gt $Newest.LastWriteTime)) {
            $Newest = $_
        }
    }

    if ($null -eq $Newest) {
        throw "$SourceName directory contains no files: $Path"
    }

    return $Newest.LastWriteTime.ToString("yyyy-MM-dd")
}


# ------------------------------------------------------------
# Preflight paths
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


# ------------------------------------------------------------
# Automatically derive all date/version labels
# ------------------------------------------------------------

Write-Host
Write-Host "Determining source versions from local files..."
Write-Host

# Build/release content version uses today's date automatically.
$BuildDate = Get-Date

$Version = $BuildDate.ToString("yyyy.MM.dd") + "-full"

# Source provenance dates use newest local file timestamps.
$AllakhazamVersion = Get-NewestFileDate `
    -Path $AllakhazamMirror `
    -SourceName "Allakhazam mirror"

$GoodsVersion = Get-NewestFileDate `
    -Path $GoodsMaps `
    -SourceName "Good's maps"

$BrewallVersion = Get-NewestFileDate `
    -Path $BrewallMaps `
    -SourceName "Brewall maps"


# ------------------------------------------------------------
# Display resolved build configuration
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " Resolved Build Configuration"
Write-Host "============================================"
Write-Host

Write-Host "Build version:"
Write-Host "  $Version"

Write-Host
Write-Host "Allakhazam version:"
Write-Host "  $AllakhazamVersion"

Write-Host
Write-Host "Good's version:"
Write-Host "  $GoodsVersion"

Write-Host
Write-Host "Brewall version:"
Write-Host "  $BrewallVersion"

Write-Host
Write-Host "Working DB:"
Write-Host "  $WorkingDb"

Write-Host
Write-Host "Final snapshot:"
Write-Host "  $SnapshotDb"

Write-Host


# ------------------------------------------------------------
# Ensure output directories exist
# ------------------------------------------------------------

New-Item `
    -ItemType Directory `
    -Force `
    -Path (Split-Path $WorkingDb -Parent) |
    Out-Null

New-Item `
    -ItemType Directory `
    -Force `
    -Path (Split-Path $SnapshotDb -Parent) |
    Out-Null


# ------------------------------------------------------------
# FULL KNOWLEDGE BUILD
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

if ($LASTEXITCODE -ne 0) {
    throw "EverQuestie full knowledge build failed with exit code $LASTEXITCODE."
}


# ------------------------------------------------------------
# Sanity check: MCP must actually be present
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " Verifying MCP Knowledge"
Write-Host "============================================"
Write-Host

$McpCheck = @'
import sqlite3
import sys

path = sys.argv[1]

conn = sqlite3.connect(path)

row = conn.execute("""
    SELECT source_name, source_kind
    FROM source_pages
    WHERE source_kind='mcp_local_snapshot'
    LIMIT 1
""").fetchone()

entities = conn.execute(
    "SELECT COUNT(*) FROM entities"
).fetchone()[0]

external_ids = conn.execute(
    "SELECT COUNT(*) FROM entity_external_ids"
).fetchone()[0]

sources = conn.execute(
    "SELECT COUNT(*) FROM source_pages"
).fetchone()[0]

conn.close()

if row is None:
    print("ERROR: MCP source is missing from the working knowledge DB.")
    sys.exit(2)

print("MCP source:", row)
print("Entities:", entities)
print("External IDs:", external_ids)
print("Source pages:", sources)
'@

$McpCheck | python - $WorkingDb

if ($LASTEXITCODE -ne 0) {
    throw "MCP verification failed. Refusing to accept incomplete full build."
}


# ------------------------------------------------------------
# Final independent route acceptance check
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

if ($LASTEXITCODE -ne 0) {
    throw "Finalized knowledge snapshot failed route acceptance."
}


# ------------------------------------------------------------
# Run complete regression suite
# ------------------------------------------------------------

Write-Host
Write-Host "============================================"
Write-Host " Running EverQuestie Regression Suite"
Write-Host "============================================"
Write-Host

python -m unittest discover `
    -s tests `
    -p "test_*.py"

if ($LASTEXITCODE -ne 0) {
    throw "EverQuestie regression suite failed."
}


# ------------------------------------------------------------
# Final artifact information
# ------------------------------------------------------------

$WorkingInfo = Get-Item $WorkingDb
$SnapshotInfo = Get-Item $SnapshotDb

$WorkingMiB = [Math]::Round(
    $WorkingInfo.Length / 1MB,
    1
)

$SnapshotMiB = [Math]::Round(
    $SnapshotInfo.Length / 1MB,
    1
)

$SnapshotHash = (
    Get-FileHash `
        -Algorithm SHA256 `
        $SnapshotDb
).Hash.ToLowerInvariant()


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
Write-Host "  EQ client       : included"
Write-Host "  Allakhazam      : included"
Write-Host "  MCP             : verified"
Write-Host "  Good's maps     : included"
Write-Host "  Brewall maps    : included"
Write-Host "  Travel manifests: automatically compiled"
Write-Host "  Route acceptance: passed"
Write-Host "  Regression tests: passed"

Write-Host
Write-Host "============================================"