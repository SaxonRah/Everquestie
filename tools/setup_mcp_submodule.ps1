param(
    [switch]$Update,
    [string]$Ref = ""
)

$ErrorActionPreference = "Stop"
$Canonical = Join-Path $PSScriptRoot "setup_mcp_builder_source.ps1"

Write-Warning "setup_mcp_submodule.ps1 is a compatibility alias. EverQuestie uses a repository-locked nested MCP builder source, not a parent Git submodule."
& $Canonical -Update:$Update -Ref $Ref
