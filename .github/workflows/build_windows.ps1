$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($env:OS -ne 'Windows_NT') { throw 'Build this Windows .exe on Windows 10/11 or use the GitHub Actions workflow.' }
$Python = Get-Command python -ErrorAction SilentlyContinue
if (!$Python) { throw 'Python 3.10+ x64 is required. Install Python from python.org and select Add Python to PATH.' }
$PyVersion = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$PyVersion -lt [version]'3.10') { throw "Python 3.10+ is required; found $PyVersion" }

New-Item -ItemType Directory -Force 'vendor','dist','build' | Out-Null
Write-Host '[1/5] Installing build dependencies...'
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

Write-Host '[2/5] Getting official PresentMon console helper...'
$Release = Invoke-RestMethod -Uri 'https://api.github.com/repos/GameTechDev/PresentMon/releases/latest' -Headers @{ 'User-Agent'='SARBA-GUI-build' }
$Asset = $Release.assets | Where-Object { $_.name -match '^PresentMon-[0-9]+(\.[0-9]+)*-x64\.exe$' } | Select-Object -First 1
if (!$Asset) { throw 'Could not find a compatible PresentMon x64 executable in the latest official release. Check the PresentMon release page and update the build script if the asset naming changed.' }
Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile 'vendor\PresentMon.exe'
if ((Get-Item 'vendor\PresentMon.exe').Length -lt 100000) { throw 'PresentMon download appears incomplete.' }

Write-Host '[3/5] Running source tests...'
python -m compileall -q app
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Source tests failed.' }

Write-Host '[4/5] Compiling SARBA-GUI.exe...'
python -m PyInstaller --noconfirm --clean --onefile --windowed --name SARBA-GUI --icon 'assets\SG.ico' --add-data 'assets\SG.ico;assets' --add-data 'assets\SG.png;assets' --add-binary 'vendor\PresentMon.exe;vendor' --paths app --distpath dist --workpath 'build\pyinstaller' --specpath build 'app\main.py'
if (!(Test-Path 'dist\SARBA-GUI.exe')) { throw 'PyInstaller did not create SARBA-GUI.exe.' }

Write-Host '[5/5] Building normal Windows installer...'
$ISCC = @("$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (!$ISCC) {
  Write-Host 'Inno Setup 6 not found. The standalone dist\SARBA-GUI.exe is ready; install Inno Setup 6 to also build a standard installer.'
} else {
  & $ISCC 'build\SARBA-GUI.iss'
  if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }
}
Get-FileHash 'dist\SARBA-GUI.exe' -Algorithm SHA256
if (Test-Path 'dist\SARBA-GUI-Setup.exe') { Get-FileHash 'dist\SARBA-GUI-Setup.exe' -Algorithm SHA256 }
Write-Host "Done. App: $Root\dist\SARBA-GUI.exe"
