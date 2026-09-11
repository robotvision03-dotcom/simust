# My SIMUST Android app

Player phone/tablet app for the public My SIMUST portal (`/login`, `/dashboard`, `/register`).

Separate from the lab operator app (`android/` → package `com.simust.playsmart`, name **SIMUST**).

| App | Folder | Package | Default URL |
|-----|--------|---------|-------------|
| **SIMUST** (operator) | `android/` | `com.simust.playsmart` | `http://157.180.47.98/operator` |
| **My SIMUST** (players) | `android-mysimust/` | `com.simust.mysimust` | `http://157.180.47.98/login` |

## Features

- Username / password login via the live portal WebView
- Adaptive layouts for phones and tablets (`sw600dp`)
- SIMUST logo as launcher icon and in-app branding
- Text size, rotation, keep-screen-on settings
- Works on mobile data or Wi‑Fi (cleartext HTTP allowed for the current public host)

## Version

- Package: `com.simust.mysimust`
- Version: **1.1** (versionCode 2)
- Targets Android 16 (API 36), minSdk 24
- Admin waiver reservations use an in-page password field (works in WebView)
- JS alert/confirm/prompt dialogs are handled natively

## Build / install / keep in sync with web + VPS

```powershell
# Preferred: push branch, update VPS HTML/API, rebuild both APKs
cd C:\Users\siama\Documents\simust
.\deploy\update-all.ps1

# Or My SIMUST APK only
cd android-mysimust
.\gradlew.bat assembleDebug
.\install-apk.bat
```

See `deploy/UPDATE_PIPELINE.txt`.