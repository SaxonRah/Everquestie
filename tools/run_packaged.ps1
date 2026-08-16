param(
    [string]$KnowledgeDb = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Entry = Join-Path $ProjectRoot "EverQuestie.py"

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

if ([string]::IsNullOrWhiteSpace($KnowledgeDb)) {
    $KnowledgeDb = Join-Path $ProjectRoot "dist\everquestie-knowledge.sqlite3"
}
$KnowledgeDb = [System.IO.Path]::GetFullPath($KnowledgeDb)
if (-not (Test-Path $KnowledgeDb -PathType Leaf)) {
    throw "Finalized EverQuestie knowledge snapshot was not found: $KnowledgeDb"
}
if (-not (Test-Path $Entry -PathType Leaf)) {
    throw "EverQuestie.py was not found: $Entry"
}

$PythonCommand = Resolve-Python $PythonExe
$PreviousKnowledge = [Environment]::GetEnvironmentVariable("EVERQUESTIE_KNOWLEDGE_DB", "Process")

Write-Host "EverQuestie packaged-runtime source launch"
Write-Host "  Knowledge: $KnowledgeDb"
Write-Host "  Python:    $PythonCommand"
Write-Host "  User state will remain separate under the normal runtime policy."
Write-Host

try {
    $env:EVERQUESTIE_KNOWLEDGE_DB = $KnowledgeDb
    Push-Location $ProjectRoot
    try {
        & $PythonCommand $Entry
        if ($LASTEXITCODE -ne 0) {
            throw "EverQuestie exited with code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($null -eq $PreviousKnowledge) {
        Remove-Item Env:EVERQUESTIE_KNOWLEDGE_DB -ErrorAction SilentlyContinue
    }
    else {
        $env:EVERQUESTIE_KNOWLEDGE_DB = $PreviousKnowledge
    }
}
