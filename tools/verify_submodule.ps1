$ErrorActionPreference = "Stop"
$Verifier = Join-Path $PSScriptRoot "verify_mcp_builder_source.py"

Write-Warning "verify_submodule.ps1 is a compatibility alias. EverQuestie verifies a repository-locked nested MCP builder source, not a parent Git submodule."

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    throw "Python was not found in PATH."
}

& $Python.Source $Verifier
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
