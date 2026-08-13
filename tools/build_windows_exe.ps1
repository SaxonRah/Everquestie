param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Entry = Join-Path $ProjectRoot "EverQuestie.py"

if (-not (Test-Path $Entry)) {
    throw "EverQuestie.py was not found at '$Entry'."
}

$Python = Get-Command py -ErrorAction SilentlyContinue
if (-not $Python) {
    throw "The Python launcher 'py' was not found in PATH."
}

& py -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Install it explicitly with: py -m pip install pyinstaller"
}

$Args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "EverQuestie"
)

if ($OneFile) {
    $Args += "--onefile"
}

$AssetDir = Join-Path $ProjectRoot "eqquest\assets"
if (Test-Path $AssetDir) {
    $Args += @("--add-data", "$AssetDir;eqquest\assets")
}

$Args += $Entry

Push-Location $ProjectRoot
try {
    & py @Args
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

Write-Host "Build complete. See: $ProjectRoot\dist"
