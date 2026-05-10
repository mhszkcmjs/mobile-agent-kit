param()
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ApkDir  = Join-Path $ProjectRoot "data\apk"
$ApkPath = Join-Path $ApkDir "ADBKeyboard.apk"
$Url     = "https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk"

# 1. adb in PATH?
$adbCmd = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adbCmd) { Write-Host "[FAIL] adb not in PATH" -ForegroundColor Red; exit 1 }

# 2. device connected?
$devLines = (& adb devices) | Select-Object -Skip 1 | Where-Object { $_ -match "device$" }
if (-not $devLines) { Write-Host "[FAIL] no device found" -ForegroundColor Red; exit 1 }
Write-Host "[ OK ] device: $($devLines | Select-Object -First 1)" -ForegroundColor Green

# 3. download APK if missing
if (-not (Test-Path $ApkPath)) {
    New-Item -ItemType Directory -Force -Path $ApkDir | Out-Null
    Write-Host "[INFO] downloading ADBKeyboard.apk..." -ForegroundColor Cyan
    $dlOk = $false
    try { Invoke-WebRequest -Uri $Url -OutFile $ApkPath -UseBasicParsing; $dlOk = $true } catch { $dlOk = $false }
    if (-not $dlOk) {
        Write-Host "[FAIL] download failed. Place ADBKeyboard.apk at: $ApkPath" -ForegroundColor Red
        exit 1
    }
}
Write-Host "[ OK ] APK: $ApkPath" -ForegroundColor Green

# 4. install
Write-Host "[INFO] adb install -r ..." -ForegroundColor Cyan
$installOut = & adb install -r $ApkPath
$installFailed = $installOut -match "Failure"
if ($installFailed) {
    Write-Host "[FAIL] install failed: $installOut" -ForegroundColor Red
    exit 1
}
Write-Host "[ OK ] ADBKeyboard installed" -ForegroundColor Green

# 5. enable IME
$null = & adb shell ime enable com.android.adbkeyboard/.AdbIME
$null = & adb shell ime set   com.android.adbkeyboard/.AdbIME

$imes = & adb shell ime list -s
$imeEnabled = $imes -match "com.android.adbkeyboard/.AdbIME"
if ($imeEnabled)      { Write-Host "[ OK ] ADBKeyboard set as IME" -ForegroundColor Green }
if (-not $imeEnabled) { Write-Host "[WARN] set IME manually: Settings->Language->Keyboards->Enable ADBKeyboard" -ForegroundColor Yellow }

Write-Host "`nDone." -ForegroundColor Green
