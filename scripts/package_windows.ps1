# Build dist\Crater\Crater.exe and, if Inno Setup is installed, dist\Crater-Windows-Setup.exe.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pip install -e ".[dev]"
pyinstaller --noconfirm packaging\crater.spec
if (Get-Command iscc -ErrorAction SilentlyContinue) {
    $version = python -c "import crater_app; print(crater_app.__version__)"
    iscc "/DAppVersion=$version" packaging\crater.iss
}
Write-Host "Built dist\Crater\Crater.exe"
