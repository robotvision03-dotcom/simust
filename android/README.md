# SIMUST Android app

Tablet and phone console that uses the same operator UI as `index.html`. Works over the public internet from any country.

## Modes

- **Public operator** (default): `http://157.180.47.98/operator` — sign in, press Realtime Play, watch live results. The Netherlands lab PC executes the test. Players can start their own session; coaches can start a player on their team.
- **Public player**: My SIMUST login and dashboard (results after a saved test).
- **Lab PC**: same Wi‑Fi as `app.py` only when you need a direct LAN link.

## Windows lab PC

`install-apk.ps1` only exists on branch `cursor/android-operator-app-c690`. `git pull` inside `android\` while you are on another branch will say “Already up to date” and will **not** create that file.

The APK path `app\build\outputs\apk\debug\app-debug.apk` is created only after a successful Gradle build. `adb` working does not mean the APK exists.

### 1. Switch to the Android branch (repo root, not `android\`)

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim"
git fetch origin
git stash
git checkout cursor/android-operator-app-c690
git pull origin cursor/android-operator-app-c690
dir android\install-apk.bat
```

You should see `install-apk.bat`. If checkout is refused, send the `git status` output.

### 2. Build and install (emulator or USB tablet)

An Android emulator counts (`emulator-5554` is fine).

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim\android"
.\install-apk.bat
```

Or without the script:

```powershell
cd "C:\Users\siama\Documents\qr-based-sport-analyzer -sim\android"
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat assembleDebug
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r app\build\outputs\apk\debug\app-debug.apk
```

If Gradle fails, open `...\android` in Android Studio, wait for sync, then **Run ▶** on `emulator-5554` (or **Build → Build APK(s)**).

### 3. After install

Open **SIMUST Play Smart**. Operator URL should stay `http://157.180.47.98/operator`.

On the Windows lab PC leave `lab.env` next to `app.py` and keep `python app.py` running. The lab pulls tablet commands about once a second and pushes live results back.

## Command-line build (any OS)

```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

On Windows use `.\gradlew.bat assembleDebug`, not `./gradlew`.
