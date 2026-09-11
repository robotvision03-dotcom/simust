# Create a Play Console upload keystore for My SIMUST (one time).
# Output: mysimust-upload.jks + keystore.properties in this folder.
# Keep BOTH files private and backed up — losing them blocks app updates.

param(
    [string]$Alias = "mysimust",
    [string]$StoreFile = "mysimust-upload.jks",
    [int]$ValidityDays = 10000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path $StoreFile) {
    Write-Host "Keystore already exists: $StoreFile"
    Write-Host "Delete it only if you intentionally want a NEW upload key (breaks Play updates unless you reset)."
    exit 1
}

$storePass = Read-Host "New keystore password (min 6 chars)" -AsSecureString
$storePassPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($storePass)
)
$keyPass = Read-Host "Key password (or same as store)" -AsSecureString
$keyPassPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($keyPass)
)
if (-not $keyPassPlain) { $keyPassPlain = $storePassPlain }

$cn = Read-Host "Your name / organization (CN)"
if (-not $cn) { $cn = "SIMUST" }

$keytool = Get-Command keytool -ErrorAction SilentlyContinue
if (-not $keytool) {
    # Common Android Studio JBR location on Windows
    $jbr = @(
        "$env:LOCALAPPDATA\Programs\Android\Android Studio\jbr\bin\keytool.exe",
        "$env:ProgramFiles\Android\Android Studio\jbr\bin\keytool.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $jbr) { throw "keytool not found. Install JDK or Android Studio." }
    $keytoolPath = $jbr
} else {
    $keytoolPath = $keytool.Source
}

& $keytoolPath -genkeypair `
    -v `
    -keystore $StoreFile `
    -alias $Alias `
    -keyalg RSA `
    -keysize 2048 `
    -validity $ValidityDays `
    -storepass $storePassPlain `
    -keypass $keyPassPlain `
    -dname "CN=$cn, OU=SIMUST, O=SIMUST, L=Unknown, S=Unknown, C=NL"

@"
storeFile=$StoreFile
storePassword=$storePassPlain
keyAlias=$Alias
keyPassword=$keyPassPlain
"@ | Set-Content -Path "keystore.properties" -Encoding ASCII

Write-Host ""
Write-Host "Created $StoreFile and keystore.properties"
Write-Host "BACK THESE UP OFFLINE. Do not commit them to git."
Write-Host "Next: .\gradlew.bat bundleRelease"
Write-Host "Then upload MySIMUST-*-release.aab in Play Console."
