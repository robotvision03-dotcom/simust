# SIMUST Android app

Tablet and phone console that uses the same operator UI as `index.html`.

## Modes

- **Public operator** (default): `http://157.180.47.98/operator` — search a player, Foundation / SF-30N, simulator, Realtime Play. Sign in as coach, manager, or admin. Commands go to the lab PC through the public host.
- **Public player**: My SIMUST login and dashboard.
- **Lab PC**: same Wi‑Fi as `app.py` (for example `http://192.168.1.10:8000`).

## Build

On a machine with Android Studio or the Android SDK:

```bash
cd android
./gradlew assembleDebug
```

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`.

Install on a device:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The lab PC must keep `lab.env` next to `app.py` so it pulls tablet commands every few seconds.
