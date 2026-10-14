$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ((Test-Path -LiteralPath 'dist\EngineerHub\EngineerHubLibrary') -or (Test-Path -LiteralPath 'dist\EngineerHub\EngineerHub.settings.json')) {
    throw 'Existing user data found in dist\EngineerHub. Back up and move that application folder before rebuilding.'
}
if (-not (Test-Path -LiteralPath '.venv-build\Scripts\python.exe')) {
    python -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create build environment' }
}
python -m pip --python '.\.venv-build\Scripts\python.exe' install --disable-pip-version-check 'pyinstaller==6.20.0'
if ($LASTEXITCODE -ne 0) { throw 'Cannot install build dependencies' }
& '.\.venv-build\Scripts\python.exe' -m PyInstaller --noconfirm --clean --onedir --windowed --name EngineerHub main.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
