$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not $env:LOCALAPPDATA) { throw 'Windows LOCALAPPDATA is required.' }
$pythonExe = Join-Path $env:LOCALAPPDATA 'zhixing-wxvideo-rd\runtime\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Python not found. Run scripts/setup.ps1 first.' }
    $pythonExe = $python.Source
}
& $pythonExe (Join-Path $PSScriptRoot 'wx_video.py') @args
exit $LASTEXITCODE
