param([string]$Python = 'python', [int]$Port = 5000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment. Use -Python with your Python 3.10+ executable.' }
}
& $venvPython -c 'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec("flask") else 1)'
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See README for mirror configuration.' }
}
New-Item -ItemType Directory -Path instance -Force | Out-Null
if (-not $env:STUDYSEAT_SECRET_KEY) {
    $secretFile = Join-Path $PSScriptRoot 'instance/.secret-key'
    if (-not (Test-Path -LiteralPath $secretFile)) {
        $secretBytes = New-Object byte[] 32
        $randomGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
        $randomGenerator.GetBytes($secretBytes)
        $randomGenerator.Dispose()
        [IO.File]::WriteAllText($secretFile, [Convert]::ToBase64String($secretBytes))
    }
    $env:STUDYSEAT_SECRET_KEY = [IO.File]::ReadAllText($secretFile).Trim()
}
& $venvPython -m flask --app studyseat init-db --demo
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
Write-Host "Study Seat: http://127.0.0.1:$Port (Ctrl+C to stop)"
& $venvPython -m flask --app studyseat run --host 127.0.0.1 --port $Port
