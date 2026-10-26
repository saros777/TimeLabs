$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required on the build machine' }
}
& .venv\Scripts\python.exe -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
$env:QT_QPA_PLATFORM = 'offscreen'
& .venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
Remove-Item Env:\QT_QPA_PLATFORM
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name TimeLabs --paths . --collect-all ortools --collect-all argon2 --hidden-import PySide6.QtPrintSupport scripts/entrypoint.py
if ($LASTEXITCODE -ne 0) { throw 'Windows bundle failed' }
Copy-Item README.md dist\TimeLabs\README.md
Copy-Item docs\STATUS.md dist\TimeLabs\STATUS.md
Compress-Archive -Path dist\TimeLabs -DestinationPath dist\TimeLabs-Windows-x64.zip -Force
Get-FileHash dist\TimeLabs-Windows-x64.zip -Algorithm SHA256 | Format-List | Out-File dist\SHA256.txt
Write-Host 'Portable bundle: dist\TimeLabs-Windows-x64.zip. Test it on a clean Windows 11 machine before distribution.'
