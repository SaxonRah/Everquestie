param(
    [switch]$Update,
    [string]$Ref = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$McpPath = Join-Path $ProjectRoot "third_party\everquest1-mcp"
$McpUrl = "https://github.com/ArtSabintsev/everquest1-mcp.git"

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $FilePath $($Arguments -join ' ')"
    }
}

Write-Host "EverQuestie MCP setup"
Write-Host "Project: $ProjectRoot"
Write-Host "MCP:     $McpPath"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found in PATH. Install Git for Windows first."
}

$IsGitCheckout = Test-Path (Join-Path $ProjectRoot ".git")

if ($IsGitCheckout) {
    Write-Host "Initializing everquest1-mcp dependency..."
    Push-Location $ProjectRoot
    try {
        & git submodule update --init --recursive -- third_party/everquest1-mcp
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Git submodule initialization failed; falling back to a direct clone."
        }
    }
    finally {
        Pop-Location
    }
}

# If the repository export/check-out does not currently contain a usable gitlink,
# or if this is a ZIP/source export, make the helper self-healing by cloning directly.
if (-not (Test-Path (Join-Path $McpPath "package.json"))) {
    if (Test-Path $McpPath) {
        $Existing = Get-ChildItem -Force $McpPath -ErrorAction SilentlyContinue
        if ($Existing) {
            throw "'$McpPath' exists but does not look like an everquest1-mcp checkout. Remove or rename it, then rerun this script."
        }
        Remove-Item -Force $McpPath -ErrorAction SilentlyContinue
    }

    Write-Host "Cloning everquest1-mcp into third_party..."
    New-Item -ItemType Directory -Force -Path (Split-Path $McpPath) | Out-Null
    Invoke-Checked git clone $McpUrl $McpPath
}

if (-not (Test-Path (Join-Path $McpPath "package.json"))) {
    throw "everquest1-mcp was not initialized correctly at '$McpPath'."
}

if ($Update) {
    Write-Host "Fetching upstream updates..."
    Invoke-Checked git -C $McpPath fetch --tags --prune

    if ($Ref) {
        Write-Host "Checking out requested ref: $Ref"
        Invoke-Checked git -C $McpPath checkout $Ref
    }
    elseif ($IsGitCheckout) {
        Push-Location $ProjectRoot
        try {
            & git submodule update --init --recursive -- third_party/everquest1-mcp
        }
        finally {
            Pop-Location
        }
    }
}
elseif ($Ref) {
    Write-Host "Checking out requested ref: $Ref"
    Invoke-Checked git -C $McpPath fetch --tags --prune
    Invoke-Checked git -C $McpPath checkout $Ref
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

$Commit = (& git -C $McpPath rev-parse HEAD).Trim()
Write-Host ""
Write-Host "everquest1-mcp is ready."
Write-Host "Commit: $Commit"
Write-Host "Path:   $McpPath"
