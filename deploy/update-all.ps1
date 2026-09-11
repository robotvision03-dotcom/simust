# Update lab + VPS + Android apps together after a web change.
#
# Usage (from repo root, PowerShell):
#   .\deploy\update-all.ps1
#   .\deploy\update-all.ps1 -Branch main -SkipAndroid
#   .\deploy\update-all.ps1 -VpsHost root@157.180.47.98
#
# What it does:
#   1) Optionally pushes current branch
#   2) SSH to VPS and runs deploy/update-vps.sh (git pull + systemctl restart)
#   3) Builds My SIMUST + operator debug APKs
#
# Prerequisites: git, SSH key for the VPS, Android SDK / Gradle wrappers.

param(
    [string]$Branch = "",
    [string]$VpsHost = "root@157.180.47.98",
    [switch]$SkipPush,
    [switch]$SkipVps,
    [switch]$SkipAndroid,
    [switch]$OperatorOnly,
    [switch]$MySimustOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Branch) {
    $Branch = (git rev-parse --abbrev-ref HEAD).Trim()
}

Write-Host "==> Repo: $Root"
Write-Host "==> Branch: $Branch"

if (-not $SkipPush) {
    Write-Host "==> Pushing origin/$Branch"
    git push -u origin "HEAD:$Branch"
}

if (-not $SkipVps) {
    Write-Host "==> Updating VPS $VpsHost (/opt/simust <- $Branch)"
    $remote = @"
export SIMUST_REPO_BRANCH='$Branch'
if [ -f /opt/simust/deploy/update-vps.sh ]; then
  bash /opt/simust/deploy/update-vps.sh
else
  cd /opt/simust && git fetch origin && git checkout '$Branch' && git pull --ff-only origin '$Branch' && systemctl restart simust
fi
"@
    ssh $VpsHost $remote
}

function Build-Apk($Dir, $Label) {
    Write-Host "==> Building $Label ($Dir)"
    Push-Location $Dir
    try {
        if (Test-Path ".\gradlew.bat") {
            & .\gradlew.bat assembleDebug --quiet
        } else {
            throw "gradlew.bat missing in $Dir"
        }
    } finally {
        Pop-Location
    }
}

if (-not $SkipAndroid) {
    if (-not $OperatorOnly) {
        Build-Apk (Join-Path $Root "android-mysimust") "My SIMUST"
        Get-ChildItem (Join-Path $Root "android-mysimust") -Filter "MySIMUST-*-debug.apk" |
            ForEach-Object { Write-Host "    APK: $($_.FullName)" }
    }
    if (-not $MySimustOnly) {
        Build-Apk (Join-Path $Root "android") "SIMUST operator"
        Get-ChildItem (Join-Path $Root "android") -Filter "SIMUST-*-debug.apk" |
            ForEach-Object { Write-Host "    APK: $($_.FullName)" }
    }
}

Write-Host ""
Write-Host "Done."
Write-Host "  Web/VPS : http://157.180.47.98/login  (hard-refresh or reopen Android app)"
Write-Host "  Install : android-mysimust\install-apk.bat   and/or   android\install-apk.bat"
Write-Host "  Rule    : any my_simust.html / index.html change that affects phones must bump the APK if native WebView code changed; HTML-only fixes ship via VPS pull alone."
