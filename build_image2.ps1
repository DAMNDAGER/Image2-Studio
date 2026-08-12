$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$candidates = @()
if ($env:IMAGE2_PYTHON) { $candidates += $env:IMAGE2_PYTHON }
if (Test-Path (Join-Path $PSScriptRoot ".build-venv\Scripts\python.exe")) { $candidates += (Join-Path $PSScriptRoot ".build-venv\Scripts\python.exe") }
$command = Get-Command python -ErrorAction SilentlyContinue
if ($command) { $candidates += $command.Source }

$python = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path $candidate)) { continue }
    & $candidate -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    throw "A Python installation with PyInstaller was not found. Install requirements-build.txt or set IMAGE2_PYTHON to a suitable interpreter."
}

foreach ($path in @("dist\Image2Studio", "build\Image2Studio", "build\Image2CLI", "Image2Studio.spec", "Image2CLI.spec")) {
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

& $python -m PyInstaller --noconfirm --clean --onedir --name Image2Studio `
    --add-data "static;static" `
    --add-data "skills;skills" `
    --hidden-import app `
    image2_server.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

& $python -m PyInstaller --noconfirm --clean --onefile --name Image2CLI `
    --distpath "dist\Image2Studio" `
    --workpath "build\Image2CLI" `
    image2_cli.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed while building Image2CLI.exe with exit code $LASTEXITCODE."
}

$releaseRoot = Join-Path $PSScriptRoot "..\Image2Studio"
$releaseApp = Join-Path $releaseRoot "Image2Studio"
if (Get-Process -Name "Image2Studio" -ErrorAction SilentlyContinue) {
    throw "Image2Studio is running. Stop the local service before rebuilding the release directory."
}
if (Test-Path $releaseApp) {
    Remove-Item -LiteralPath $releaseApp -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $releaseApp | Out-Null
Copy-Item -Path "dist\Image2Studio\*" -Destination $releaseApp -Recurse -Force
Copy-Item -Path "start_image2.bat", "start_image2.ps1" -Destination $releaseRoot -Force
Copy-Item -Path "README.md" -Destination (Join-Path $releaseRoot "README.md") -Force
Copy-Item -Path "LICENSE" -Destination $releaseRoot -Force

Write-Host "Built dist\Image2Studio and synchronized ..\Image2Studio"
