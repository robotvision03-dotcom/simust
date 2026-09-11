# My SIMUST Android app

Player phone/tablet app for the public My SIMUST portal (`/login`, `/dashboard`, `/register`).

| App | Folder | Package | Default URL |
|-----|--------|---------|-------------|
| **SIMUST** (operator) | `android/` | `com.simust.playsmart` | lab `/operator` |
| **My SIMUST** (players) | `android-mysimust/` | `com.simust.mysimust` | `https://my.simust.com/login` |

## Version

- Package: `com.simust.mysimust` (never change after Play publish)
- Version: **1.2** (versionCode **3**)
- Targets Android 16 (API 36), minSdk 24
- Privacy: https://my.simust.com/privacy

## Google Play

Follow **[PLAY_STORE.md](PLAY_STORE.md)**.

```powershell
cd android-mysimust
.\create-upload-keystore.ps1   # once — back up the .jks
.\gradlew.bat bundleRelease    # → MySIMUST-1.2-release.aab
```

Upload the `.aab` at https://play.google.com/console

## Debug install (lab / sideload)

```powershell
.\gradlew.bat assembleDebug
.\install-apk.bat
```

Keep web + VPS + APKs in sync: `..\deploy\update-all.ps1` (see `deploy/UPDATE_PIPELINE.txt`).
