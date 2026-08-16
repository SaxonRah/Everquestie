param(
    [switch]$Update,
    [string]$Ref = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$McpPath = Join-Path $ProjectRoot "third_party\everquest1-mcp"
$LockPath = Join-Path $ProjectRoot "third_party\everquest1-mcp.lock.json"

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Normalize-GitRemote {
    param([string]$Value)
    $Normalized = ([string]$Value).Trim().TrimEnd('/').ToLowerInvariant()
    if ($Normalized.EndsWith('.git')) {
        $Normalized = $Normalized.Substring(0, $Normalized.Length - 4)
    }
    return $Normalized
}

if (-not (Test-Path $LockPath -PathType Leaf)) {
    throw "EverQuestie MCP source lock is missing: $LockPath"
}

$McpLock = Get-Content $LockPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$McpLock.schema_version -ne 1) {
    throw "Unsupported MCP source lock schema in '$LockPath'."
}
$McpUrl = ([string]$McpLock.repository).Trim()
$LockedCommit = ([string]$McpLock.commit).Trim().ToLowerInvariant()
$LockedVersion = ([string]$McpLock.package_version).Trim()
if (-not $McpUrl) {
    throw "MCP source lock repository is missing."
}
if ($LockedCommit -notmatch '^[0-9a-f]{40}$') {
    throw "MCP source lock commit must be a full 40-character Git SHA."
}
if (-not $LockedVersion) {
    throw "MCP source lock package_version is missing."
}

Write-Host "EverQuestie MCP setup"
Write-Host "Project: $ProjectRoot"
Write-Host "MCP:     $McpPath"
Write-Host "Lock:    $LockPath"
Write-Host "Commit:  $LockedCommit"
Write-Host "Version: $LockedVersion"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found in PATH. Install Git for Windows first."
}

# The dependency is intentionally a normal nested clone rather than a parent-repo
# submodule. That gives Git checkouts and downloaded source ZIPs the same layout while
# the tracked lock file supplies the reproducible revision contract.
if (-not (Test-Path (Join-Path $McpPath "package.json") -PathType Leaf)) {
    if (Test-Path $McpPath) {
        $Existing = Get-ChildItem -Force $McpPath -ErrorAction SilentlyContinue
        if ($Existing) {
            throw "'$McpPath' exists but does not look like an everquest1-mcp checkout. Remove or rename it, then rerun this script."
        }
        Remove-Item -Force $McpPath -ErrorAction SilentlyContinue
    }

    Write-Host "Cloning locked everquest1-mcp source into third_party..."
    New-Item -ItemType Directory -Force -Path (Split-Path $McpPath) | Out-Null
    Invoke-Checked git clone $McpUrl $McpPath
}

if (-not (Test-Path (Join-Path $McpPath "package.json") -PathType Leaf)) {
    throw "everquest1-mcp was not initialized correctly at '$McpPath'."
}

$IsMcpGit = (& git -C $McpPath rev-parse --is-inside-work-tree 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or $IsMcpGit -ne "true") {
    throw "'$McpPath' is not a Git checkout. The builder source must retain exact commit provenance."
}

$Origin = (& git -C $McpPath remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or -not $Origin) {
    throw "everquest1-mcp checkout has no readable origin remote."
}
if ((Normalize-GitRemote $Origin) -ne (Normalize-GitRemote $McpUrl)) {
    throw "everquest1-mcp origin '$Origin' does not match locked repository '$McpUrl'."
}

if ($Ref) {
    Write-Warning "Developer override requested with -Ref '$Ref'. This checkout will not satisfy the canonical full-build lock unless it resolves to $LockedCommit."
    $Dirty = (& git -C $McpPath status --porcelain)
    if ($Dirty) {
        throw "everquest1-mcp has local changes. Refusing to change revisions in a dirty checkout."
    }
    Invoke-Checked git -C $McpPath fetch --tags --prune origin
    Invoke-Checked git -C $McpPath checkout --detach $Ref
}
else {
    $CurrentCommit = (& git -C $McpPath rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read everquest1-mcp HEAD."
    }

    if ($Update) {
        Write-Host "Refreshing upstream refs without changing the repository lock..."
        Invoke-Checked git -C $McpPath fetch --tags --prune origin
    }

    if ($CurrentCommit -ne $LockedCommit) {
        $Dirty = (& git -C $McpPath status --porcelain)
        if ($Dirty) {
            throw "everquest1-mcp HEAD is not the locked revision and the checkout has local changes. Commit/stash/remove those changes before setup can switch revisions."
        }

        # A normal clone contains the historical commit. If a partial/shallow checkout
        # does not, fetch refs once and then fetch the exact object as a final fallback.
        & git -C $McpPath cat-file -e "$LockedCommit^{commit}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Invoke-Checked git -C $McpPath fetch --tags --prune origin
            & git -C $McpPath cat-file -e "$LockedCommit^{commit}" 2>$null
            if ($LASTEXITCODE -ne 0) {
                Invoke-Checked git -C $McpPath fetch origin $LockedCommit
            }
        }
        Write-Host "Checking out repository-locked revision: $LockedCommit"
        Invoke-Checked git -C $McpPath checkout --detach $LockedCommit
    }
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found in PATH. Install Node.js 18+ first."
}

Write-Host "Installing/building everquest1-mcp..."
Push-Location $McpPath
try {
    Invoke-Checked npm install
    Invoke-Checked npm run build
}
finally {
    Pop-Location
}

$Commit = (& git -C $McpPath rev-parse HEAD).Trim().ToLowerInvariant()
$Package = Get-Content (Join-Path $McpPath "package.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$PackageVersion = ([string]$Package.version).Trim()

if (-not $Ref) {
    if ($Commit -ne $LockedCommit) {
        throw "MCP setup ended at $Commit instead of repository lock $LockedCommit."
    }
    if ($PackageVersion -ne $LockedVersion) {
        throw "MCP package version '$PackageVersion' does not match repository lock '$LockedVersion'."
    }
}

Write-Host ""
Write-Host "everquest1-mcp is ready."
Write-Host "Commit:  $Commit"
Write-Host "Version: $PackageVersion"
Write-Host "Path:    $McpPath"
if ($Ref) {
    Write-Host "Mode:    developer override (canonical full builds remain locked to $LockedCommit)"
}
else {
    Write-Host "Mode:    repository-locked builder source"
}
