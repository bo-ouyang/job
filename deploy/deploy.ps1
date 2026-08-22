$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$conda = Get-Command conda -ErrorAction Stop

Push-Location $projectRoot
try {
    & $conda.Source "run" "--no-capture-output" "-n" "job" "python" (Join-Path $PSScriptRoot "deploy.py") @args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
