$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$McpPath = Join-Path $ProjectRoot "third_party\everquest1-mcp"

if (-not (Test-Path (Join-Path $McpPath "package.json"))) {
    throw "everquest1-mcp is not initialized. Run .\tools\setup_mcp_submodule.cmd first."
}

$Commit = (& git -C $McpPath rev-parse HEAD).Trim()
Write-Host "everquest1-mcp path:   $McpPath"
Write-Host "everquest1-mcp commit: $Commit"
