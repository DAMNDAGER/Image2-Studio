$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-Image2Service {
    param([string]$DataRoot)
    $tokenPath = Join-Path $DataRoot ".image2-token"
    if (-not (Test-Path -LiteralPath $tokenPath)) { return $false }
    try {
        $token = (Get-Content -Raw -LiteralPath $tokenPath).Trim()
        if (-not $token) { return $false }
        $headers = @{ "X-Image2-Local-Token" = $token }
        $response = Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

$listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $knownRoots = @($PSScriptRoot, (Join-Path $PSScriptRoot "Image2Studio"), (Join-Path $PSScriptRoot "..\Image2Studio\Image2Studio"))
    foreach ($knownRoot in $knownRoots) {
        if (Test-Image2Service -DataRoot $knownRoot) {
            Write-Host "Image2 is already running at http://127.0.0.1:8765"
            exit 0
        }
    }
    throw "Port 8765 is already used by another service. Stop it before starting Image2."
}

$bundledCandidates = @(
    (Join-Path $PSScriptRoot "dist\Image2Studio\Image2Studio.exe"),
    (Join-Path $PSScriptRoot "Image2Studio\Image2Studio.exe"),
    (Join-Path $PSScriptRoot "..\Image2Studio\Image2Studio\Image2Studio.exe")
)
$bundled = $bundledCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($bundled) {
    $bundleDir = Split-Path $bundled -Parent
    if (-not (Test-Path (Join-Path $bundleDir "_internal"))) {
        throw "The packaged Image2 runtime is incomplete: _internal is missing beside Image2Studio.exe."
    }
    & $bundled
} else {
    $python = $env:IMAGE2_PYTHON
    if (-not $python) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $python = $command.Source }
    }
    if (-not $python) {
        throw "Python was not found. Build dist\Image2Studio first or install Python."
    }
    & $python -c "import fastapi, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "The selected Python does not have FastAPI and Uvicorn. Install requirements.txt or use the packaged release."
    }
    & $python -m uvicorn app:app --host 127.0.0.1 --port 8765
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
