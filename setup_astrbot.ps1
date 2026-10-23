param(
    [string]$Python = "python",
    [string]$Runtime = (Join-Path (Split-Path $PSScriptRoot -Parent) "AstrBot"),
    [switch]$ActivateNapCat
)
$ErrorActionPreference = "Stop"
$runtimePath = [IO.Path]::GetFullPath($Runtime)
$repoPath = [IO.Path]::GetFullPath($PSScriptRoot)
if ($runtimePath.StartsWith($repoPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or $runtimePath -eq $repoPath) {
    throw "Runtime must be outside the Git repository."
}
New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
$runtimePython = Join-Path $runtimePath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $runtimePython)) {
    & $Python -m venv (Join-Path $runtimePath ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment (requires Python 3.12+)." }
}
& $runtimePython -m pip install --index-url https://pypi.org/simple "AstrBot==4.29.1" python-dotenv -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install AstrBot dependencies." }
$migrationArgs = @((Join-Path $PSScriptRoot "scripts\migrate_local.py"), "--runtime", $runtimePath)
if (Test-Path -LiteralPath (Join-Path $runtimePath "data\cmd_config.json")) {
    $migrationArgs += "--sync-only"
}
if ($ActivateNapCat) {
    $napcatRoot = Join-Path (Split-Path $PSScriptRoot -Parent) "NapCat.44498.Shell"
    $migrationArgs += @("--activate-napcat", $napcatRoot)
}
$env:PYTHONUTF8 = "1"
& $runtimePython @migrationArgs
if ($LASTEXITCODE -ne 0) { throw "Migration did not complete. Existing NoneBot files were kept." }
Write-Host "Ready. Start start.bat; login details are in the runtime's local-access.txt."
