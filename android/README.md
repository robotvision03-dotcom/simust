# SIMUST Android app

Tablet and phone console that uses the same operator UI as `index.html`. Works over the public internet from any country.

## Modes

- **Public operator** (default): `http://157.180.47.98/operator` — sign in, press Realtime Play, watch live results. The Netherlands lab PC executes the test. Players can start their own session; coaches can start a player on their team.
- **Public player**: My SIMUST login and dashboard (results after a saved test).
- **Lab PC**: same Wi‑Fi as `app.py` only when you need a direct LAN link.

## Build

On a machine with Android Studio or the Android SDK:

```bash
cd android
./gradlew assembleDebug
```

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`.

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Keep `lab.env` next to `app.py` on the lab PC and leave the app running. The lab pulls tablet commands about once a second and pushes live results back.
