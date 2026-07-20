# Optionaler --onefile-Build (eine grosse .exe statt Verzeichnis).
#
# Vorteil: portabel als Single-File-Drag-and-Drop.
# Nachteil: jedes Programm-Start entpackt PyInstaller die Bundles erst
#          ins Temp-Verzeichnis (~2-4 s zusätzliche Startzeit).
#
# Voraussetzungen identisch zu build.ps1.

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Split-Path -Parent $here
$entry = Join-Path $project "src\sprichblitz_client\__main__.py"
$iconPath = Join-Path $project "assets\icon.ico"

$iconArgs = @()
if (Test-Path $iconPath) {
    $iconArgs = @("--icon", $iconPath)
} else {
    Write-Warning "assets\icon.ico fehlt – Build verwendet Default-PyInstaller-Icon."
}

function Stop-RunningSprichblitz {
    # PyInstaller --noconfirm scheitert, wenn die alte .exe noch läuft.
    $proc = Get-Process -Name "Sprichblitz" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "==> Sprichblitz läuft noch – wird beendet" -ForegroundColor Yellow
        Stop-Process -Name "Sprichblitz" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
}

Push-Location $project
try {
    Stop-RunningSprichblitz

    Write-Host "==> PyInstaller --onefile" -ForegroundColor Cyan
    uv run pyinstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name Sprichblitz `
        --hidden-import customtkinter `
        --hidden-import pystray `
        --hidden-import pystray._win32 `
        --hidden-import PIL.Image `
        --hidden-import keyring.backends.Windows `
        --hidden-import sounddevice `
        --hidden-import windows_toasts `
        --collect-data customtkinter `
        --copy-metadata customtkinter `
        @iconArgs `
        $entry
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "==> Build fehlgeschlagen (pyinstaller exit $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "    Mögliche Ursachen:" -ForegroundColor Yellow
        Write-Host "    - Eine alte Sprichblitz-Instanz hält dist\Sprichblitz.exe offen"
        Write-Host "    - Defender / Indexierungsdienst hält Dateien offen"
        Write-Host "    - Manueller Fix: dist\ und build\ löschen, ggf. Reboot"
        throw "pyinstaller exit $LASTEXITCODE"
    }
    Write-Host ""
    Write-Host "==> Fertig. Single-File: dist\Sprichblitz.exe" -ForegroundColor Green
} finally {
    Pop-Location
}
