$ErrorActionPreference = "Stop"
$Verifier = Join-Path $PSScriptRoot "verify_mcp_builder_source.py"

Write-Warning "verify_submodule.ps1 is a compatibility alias. EverQuestie verifies a repository-locked nested MCP builder source, not a parent Git submodule."

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Verifier
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py $Verifier
}
else {
    throw "Python was not found in PATH."
}

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
