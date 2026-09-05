# SIMUST Android app

Tablet and phone console that uses the same operator UI as `index.html`. Works over the public internet — Wi‑Fi or tablet SIM data — from any country.

## Modes

- **Public operator** (default): `http://157.180.47.98/operator` — sign in, press Realtime Play, watch live results. The Netherlands lab PC executes the test.
- **Public player**: My SIMUST login and dashboard.
- **Lab PC**: same Wi‑Fi as `app.py` only when you need a direct LAN link.

## Tablet settings (adjustable)

Open **Settings** in the app menu:

- **Text size** slider, plus Compact / Standard / Large
- **Keep screen on** during a test
- **Rotation**: auto, landscape, or portrait
- Public host and lab PC address

Pinch-zoom also works on the operator console. The toolbar shows whether the lab is online and whether the tablet is on **SIM / mobile data** or Wi‑Fi.

Default public host: `http://157.180.47.98`. Leave `app.py` running on the lab PC with `lab.env` so Realtime Play works worldwide.

## Install on a real tablet

Copy `app-debug.apk` onto the tablet (USB, Drive, or email) and open it. Allow install from that source if Android asks.

Or with a USB cable and the SDK:

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim"
git pull origin cursor/android-operator-app-c690
cd android
.\install-apk.bat
```

On the tablet: Developer options → USB debugging ON. Wi‑Fi or SIM data both work. Operator URL should stay `http://157.180.47.98/operator`.

## Windows lab PC

`install-apk.ps1` / `install-apk.bat` only exist on branch `cursor/android-operator-app-c690`.

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim"
git fetch origin
git stash
git checkout cursor/android-operator-app-c690
git pull origin cursor/android-operator-app-c690
cd android
.\install-apk.bat
```

If Gradle says only `What went wrong: 25.0.2`, pull again — this branch uses Gradle 9.3.1 for Android Studio’s Java 25.

## Command-line build

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

On Windows use `.\gradlew.bat assembleDebug`.
