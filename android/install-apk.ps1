# Build the SIMUST debug APK and install it on a USB tablet/phone.
# Usage (PowerShell, from this folder):
#   powershell -ExecutionPolicy Bypass -File .\install-apk.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Find-AndroidSdk {
    $candidates = @(
        $env:ANDROID_HOME,
        $env:ANDROID_SDK_ROOT,
        (Join-Path $env:LOCALAPPDATA "Android\Sdk"),
        (Join-Path $env:USERPROFILE "AppData\Local\Android\Sdk"),
        "C:\Android\Sdk"
    ) | Where-Object { $_ }
    foreach ($path in $candidates) {
        if (Test-Path (Join-Path $path "platform-tools\adb.exe")) {
            return $path
        }
    }
    return $null
}

function Find-JavaHome {
    if ($env:JAVA_HOME -and (Test-Path (Join-Path $env:JAVA_HOME "bin\java.exe"))) {
        return $env:JAVA_HOME
    }
    $studioJbr = @(
        "C:\Program Files\Android\Android Studio\jbr",
        (Join-Path $env:LOCALAPPDATA "Programs\Android Studio\jbr")
    )
    foreach ($path in $studioJbr) {
        if (Test-Path (Join-Path $path "bin\java.exe")) {
            return $path
        }
    }
    $java = Get-Command java -ErrorAction SilentlyContinue
    if ($java) {
        return (Split-Path (Split-Path $java.Source))
    }
    return $null
}

$sdk = Find-AndroidSdk
if (-not $sdk) {
    Write-Host @"
Android SDK not found. Install Android Studio first:
  https://developer.android.com/studio

Then open this folder in Android Studio:
  $Root

After Studio finishes syncing, either:
  1. Run this script again, or
  2. In Studio: Build > Build APK(s), then Run on your USB tablet.
"@
    exit 1
}

$javaHome = Find-JavaHome
if ($javaHome) {
    $env:JAVA_HOME = $javaHome
}

$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
$adb = Join-Path $sdk "platform-tools\adb.exe"
$localProps = Join-Path $Root "local.properties"
if (-not (Test-Path $localProps)) {
    $sdkDir = $sdk -replace "\\", "/"
    Set-Content -Path $localProps -Value "sdk.dir=$sdkDir"
}

Write-Host "SDK : $sdk"
Write-Host "Java: $($env:JAVA_HOME)"
Write-Host "adb : $adb"
if ($env:JAVA_HOME) {
    & "$env:JAVA_HOME\bin\java.exe" -version
}
Write-Host ""
Write-Host "Stopping old Gradle daemons (Java 25 needs Gradle 9)..."
& "$Root\gradlew.bat" --stop | Out-Null
Write-Host "Building debug APK..."
& "$Root\gradlew.bat" assembleDebug
if ($LASTEXITCODE -ne 0) {
    Write-Host "Gradle build failed. Keep this PC online so Gradle 9 can download."
    Write-Host "If Studio asks for SDK Platform 36 (Android 16) or Build-Tools 36, accept it, then Build > Build APK(s)."
    exit $LASTEXITCODE
}

$apk = Join-Path $Root "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) {
    Write-Host "APK was not created at $apk"
    exit 1
}
$named = Join-Path $Root "SIMUST-2.3-debug.apk"
$flip = Join-Path $Root "SIMUST-ZFlip6-2.3-debug.apk"
Copy-Item $apk $named -Force
Copy-Item $apk $flip -Force
Copy-Item $apk (Join-Path (Split-Path $apk) "SIMUST-2.3-debug.apk") -Force
Write-Host "APK ready:"
Write-Host "  $named"
Write-Host "  $flip"
Write-Host "  $apk"
Write-Host "  (same file; Gradle always names the build app-debug.apk)"

Write-Host ""
Write-Host "Looking for a USB device..."
& $adb start-server | Out-Null
& $adb devices
$devices = & $adb devices | Select-Object -Skip 1 | Where-Object { $_ -match "device$" }
if (-not $devices) {
    Write-Host @"

No tablet/phone found. On the device:
  Settings > About tablet > tap Build number 7 times
  Settings > Developer options > USB debugging = ON
  Plug in USB, accept the RSA prompt, then run this script again.

You can also copy the APK to the tablet and open it:
  $apk
"@
    exit 1
}

Write-Host "Installing $apk"
& $adb uninstall com.simust.playsmart | Out-Null
& $adb install -r $apk
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Installed. Open SIMUST on the Z Flip 6."
Write-Host "Operator URL should stay: http://157.180.47.98/operator"
Write-Host "Use the phone SIM or Wi-Fi. Leave the Windows lab app.py running."
