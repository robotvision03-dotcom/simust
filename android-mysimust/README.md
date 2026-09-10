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
- Version: **1.0** (versionCode 1)
- Targets Android 16 (API 36), minSdk 24

## Build / install

```powershell
cd android-mysimust
.\gradlew.bat assembleDebug
.\install-apk.bat
```

APK outputs:

- `android-mysimust/MySIMUST-1.0-debug.apk`
- `android-mysimust/app/build/outputs/apk/debug/app-debug.apk`

Both **SIMUST** and **My SIMUST** can be installed on the same device (different packages).
