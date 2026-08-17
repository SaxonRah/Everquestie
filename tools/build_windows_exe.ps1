param(
    [switch]$OneFile,
    [string]$KnowledgeDb = "",
    [string]$DistPath = "",
    [string]$PythonExe = "",
    [switch]$CleanOutput
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Entry = Join-Path $ProjectRoot "EverQuestie.py"
$KnowledgeName = "everquestie-knowledge.sqlite3"

function Resolve-OutputPath([string]$Value, [string]$BasePath) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return [System.IO.Path]::GetFullPath((Join-Path $BasePath "dist"))
    }
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Value))
}

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

if (-not (Test-Path $Entry -PathType Leaf)) {
    throw "EverQuestie.py was not found at '$Entry'."
}

$PythonCommand = Resolve-Python $PythonExe
& $PythonCommand -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed for '$PythonCommand'. Install it with: `"$PythonCommand`" -m pip install pyinstaller"
}

$ResolvedDist = Resolve-OutputPath $DistPath $ProjectRoot
New-Item -ItemType Directory -Force -Path $ResolvedDist | Out-Null

$KnowledgeResolved = ""
$KnowledgeSourceHash = ""
$KnowledgeSourceBytes = 0
if (-not [string]::IsNullOrWhiteSpace($KnowledgeDb)) {
    $KnowledgeResolved = (Resolve-Path $KnowledgeDb -ErrorAction Stop).Path
    if (-not (Test-Path $KnowledgeResolved -PathType Leaf)) {
        throw "Knowledge DB was not found at '$KnowledgeResolved'."
    }
    if ((Split-Path $KnowledgeResolved -Leaf).ToLowerInvariant() -ne $KnowledgeName) {
        throw "Knowledge DB must be named '$KnowledgeName' so packaged runtime can locate it."
    }
    $KnowledgeSourceHash = (Get-FileHash -Algorithm SHA256 $KnowledgeResolved).Hash.ToLowerInvariant()
    $KnowledgeSourceBytes = (Get-Item $KnowledgeResolved).Length
}

$Target = if ($OneFile) {
    Join-Path $ResolvedDist "EverQuestie.exe"
}
else {
    Join-Path $ResolvedDist "EverQuestie"
}
if ($CleanOutput -and (Test-Path $Target)) {
    Remove-Item -Recurse -Force $Target
}

$PyInstallerWork = Join-Path $ProjectRoot "build\pyinstaller"
$PyInstallerSpec = Join-Path $ProjectRoot "build\pyinstaller-spec"
New-Item -ItemType Directory -Force -Path $PyInstallerWork | Out-Null
New-Item -ItemType Directory -Force -Path $PyInstallerSpec | Out-Null

$Args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "EverQuestie",
    "--distpath", $ResolvedDist,
    "--workpath", $PyInstallerWork,
    "--specpath", $PyInstallerSpec
)

if ($OneFile) {
    $Args += "--onefile"
}

$AssetDir = Join-Path $ProjectRoot "eqquest\assets"
if (Test-Path $AssetDir -PathType Container) {
    $Args += @("--add-data", "$AssetDir;eqquest\assets")
}

# One-file builds must embed the immutable snapshot because there is no application
# directory to ship beside the executable. One-folder builds deliberately keep the
# snapshot as a separate file next to EverQuestie.exe so a future updater can replace
# knowledge without touching the player's writable user-state DB.
if ($OneFile -and $KnowledgeResolved) {
    $Args += @("--add-data", "$KnowledgeResolved;.")
}

$Args += $Entry

Push-Location $ProjectRoot
try {
    & $PythonCommand @Args
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

if ($KnowledgeResolved) {
    $KnowledgeAfterBuildHash = (Get-FileHash -Algorithm SHA256 $KnowledgeResolved).Hash.ToLowerInvariant()
    $KnowledgeAfterBuildBytes = (Get-Item $KnowledgeResolved).Length
    if ($KnowledgeAfterBuildHash -ne $KnowledgeSourceHash -or $KnowledgeAfterBuildBytes -ne $KnowledgeSourceBytes) {
        throw "Knowledge snapshot changed while the Windows package was being built. Build output is not trusted."
    }
}

if (-not $OneFile -and $KnowledgeResolved) {
    $PackagedKnowledge = Join-Path $Target $KnowledgeName
    Copy-Item -Force $KnowledgeResolved $PackagedKnowledge
    if (-not (Test-Path $PackagedKnowledge -PathType Leaf)) {
        throw "Windows build completed but the packaged knowledge snapshot is missing: $PackagedKnowledge"
    }
    $PackagedKnowledgeHash = (Get-FileHash -Algorithm SHA256 $PackagedKnowledge).Hash.ToLowerInvariant()
    $PackagedKnowledgeBytes = (Get-Item $PackagedKnowledge).Length
    if ($PackagedKnowledgeHash -ne $KnowledgeSourceHash -or $PackagedKnowledgeBytes -ne $KnowledgeSourceBytes) {
        throw "Packaged knowledge snapshot does not match the source knowledge artifact byte-for-byte."
    }
}

if (-not (Test-Path $Target)) {
    throw "PyInstaller reported success but the expected output was not found: $Target"
}

Write-Host "Build complete: $Target"
Write-Host "Python interpreter: $PythonCommand"
if ($KnowledgeResolved) {
    if ($OneFile) {
        Write-Host "Knowledge snapshot embedded in one-file executable: $KnowledgeResolved"
    }
    else {
        Write-Host "Knowledge snapshot packaged beside executable: $(Join-Path $Target $KnowledgeName)"
        Write-Host "Knowledge snapshot SHA-256 verified after copy: $KnowledgeSourceHash"
    }
}