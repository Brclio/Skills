$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not $env:LOCALAPPDATA) { throw 'Windows LOCALAPPDATA is required.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $env:LOCALAPPDATA 'zhixing-wxvideo-rd\runtime'
$pythonExe = Join-Path $runtime 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonExe)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Python 3.10+ not found on PATH.' }
    & $python.Source -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required.' }
    & $python.Source -m venv $runtime
    if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated Python environment.' }
}

& $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Playwright installation failed.' }
Write-Output 'Dependencies installed. No root certificate, system proxy, or bundled browser was installed.'
& $pythonExe (Join-Path $PSScriptRoot 'wx_video.py') doctor
exit $LASTEXITCODE
