$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$Candidates = @(
    (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
)
$Python = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) {
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if ($Command) { $Python = $Command.Source }
}
if (-not $Python) { throw "Python 3.11+ не найден" }

$env:PATH = "$ProjectRoot;$env:PATH"
Set-Location -LiteralPath $ProjectRoot
Write-Host "Meeting workspace: http://127.0.0.1:8000"
& $Python -m uvicorn server:app --host 127.0.0.1 --port 8000
