# SIMUST Android app

Phone and tablet console that uses the same operator UI as `index.html`. Works over the public internet — Wi‑Fi or phone SIM data — from any country.

## Galaxy Z Flip 6 (Android 16)

This is the supported phone model for remote operator use.

- Package: `com.simust.playsmart`
- Version: **2.3** (versionCode 5)
- Targets **Android 16** (API 36)
- Uses the **phone internet** (SIM or Wi‑Fi). It does not need the lab Wi‑Fi.
- Default operator URL: `http://157.180.47.98/operator`
- Cover screen and inner screen both work. Rotation is auto.

If a previous SIMUST APK would not install or would not open, uninstall that old app first, then install **2.3**. This project uses Android Gradle Plugin 9, which compiles Kotlin automatically. Build with Gradle 9.3.1 and SDK Platform 36.

## Modes

- **Public operator** (default): `http://157.180.47.98/operator` — sign in, press Realtime Play, watch live results. The lab PC executes the test.
- **Public player**: My SIMUST login and dashboard.
- **Lab PC**: same Wi‑Fi as `app.py` only when you need a direct LAN link.

## Phone settings

Open **Settings** in the app menu:

- **Text size** slider, plus Compact / Standard / Large
- **Keep screen on** during a test
- **Rotation**: auto, landscape, or portrait
- Public host and lab PC address

Pinch-zoom also works on the operator console. The toolbar shows **Lab offline.** or Lab online, and whether the phone is on **SIM / mobile data** or Wi‑Fi.

## Install on a Z Flip 6

Gradle writes:

`android/app/build/outputs/apk/debug/app-debug.apk`

After `assembleDebug` a copy is also saved as:

- `android/SIMUST-2.3-debug.apk`
- `android/SIMUST-ZFlip6-2.3-debug.apk`

Copy either file onto the phone (USB, Drive, or email) and open it.

1. Settings → Security → install unknown apps → allow the Files or Chrome app.
2. Open the APK and tap Install.
3. If Android says the app is already installed and conflicts, uninstall the old SIMUST first.
4. Open SIMUST. Leave mode on **Public operator**.
5. Turn on **mobile data or Wi‑Fi**. You do not need the lab network.
6. Sign in and start Realtime Play. The public host talks to the lab.

Or with a USB cable:

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim"
git pull origin cursor/android-operator-app-c690
cd android
.\install-apk.bat
```

On the phone: Developer options → USB debugging ON. Accept the RSA prompt.

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

If Studio asks for **SDK Platform 36** (Android 16) or Build-Tools 36, accept it.

## Command-line build

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

On Windows use `.\gradlew.bat assembleDebug`.
