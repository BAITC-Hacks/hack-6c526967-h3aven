$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$Candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
)
$Python = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Python) {
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if ($Command) { $Python = $Command.Source }
}
if (-not $Python) { throw "Установите Python 3.11+" }

$Venv = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path -LiteralPath $Venv)) {
    & $Python -m venv $Venv
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

$env:PATH = "$ProjectRoot;$env:PATH"
& $VenvPython -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
Write-Host "Готово. Запуск: .\run.ps1"
