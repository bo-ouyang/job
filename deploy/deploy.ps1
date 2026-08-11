$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Get-Command python -ErrorAction Stop

Push-Location $projectRoot
try {
    & $python.Source (Join-Path $PSScriptRoot "deploy.py") @args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
