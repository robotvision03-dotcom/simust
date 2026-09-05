# SIMUST Android app

Tablet and phone console that uses the same operator UI as `index.html`. Works over the public internet from any country.

## Modes

- **Public operator** (default): `http://157.180.47.98/operator` — sign in, press Realtime Play, watch live results. The Netherlands lab PC executes the test. Players can start their own session; coaches can start a player on their team.
- **Public player**: My SIMUST login and dashboard (results after a saved test).
- **Lab PC**: same Wi‑Fi as `app.py` only when you need a direct LAN link.

## Windows lab PC (PowerShell)

`adb` is not on PATH until Android Studio / the SDK is installed. Do **not** run `adb` from a random folder.

### 1. Install Android Studio

https://developer.android.com/studio

Open this folder (not the repo root):

`C:\Users\siama\Documents\qr-based-sport-analyzer -sim\android`

Let Gradle sync finish. If Studio asks for an SDK, accept the default.

### 2. One-command build + install

On the tablet: **Developer options → USB debugging ON**, then plug in USB.

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim\android"
git pull
powershell -ExecutionPolicy Bypass -File .\install-apk.ps1
```

That script finds Studio’s SDK, builds the APK, and calls `adb.exe` by full path.

### 3. Or build in Android Studio

**Build → Build APK(s)** (or **Run ▶** on the USB tablet).

The APK lands at:

`android\app\build\outputs\apk\debug\app-debug.apk`

To install from PowerShell without putting `adb` on PATH:

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim\android"
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r app\build\outputs\apk\debug\app-debug.apk
```

If `adb devices` is empty: unlock the tablet, accept the USB debugging prompt, try another cable/port.

You can also copy `app-debug.apk` onto the tablet and open it (allow install from Files).

### 4. After install

Open **SIMUST Play Smart**. Operator URL should stay `http://157.180.47.98/operator`.

On the Windows lab PC leave `lab.env` next to `app.py` and keep `python app.py` running. The lab pulls tablet commands about once a second and pushes live results back.

## Command-line build (any OS)

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

On Windows use `.\gradlew.bat assembleDebug`, not `./gradlew`.
