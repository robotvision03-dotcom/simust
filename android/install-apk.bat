@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not defined ANDROID_HOME if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
if not defined ANDROID_HOME if exist "%USERPROFILE%\AppData\Local\Android\Sdk\platform-tools\adb.exe" set "ANDROID_HOME=%USERPROFILE%\AppData\Local\Android\Sdk"
if not defined ANDROID_SDK_ROOT set "ANDROID_SDK_ROOT=%ANDROID_HOME%"

if not defined JAVA_HOME if exist "%ProgramFiles%\Android\Android Studio\jbr\bin\java.exe" set "JAVA_HOME=%ProgramFiles%\Android\Android Studio\jbr"
if not defined JAVA_HOME if exist "%LOCALAPPDATA%\Programs\Android Studio\jbr\bin\java.exe" set "JAVA_HOME=%LOCALAPPDATA%\Programs\Android Studio\jbr"

if not defined ANDROID_HOME (
  echo Android SDK not found. Install Android Studio, open this folder, then run this again.
  echo Folder: %cd%
  exit /b 1
)

if not exist "local.properties" (
  echo sdk.dir=%ANDROID_HOME:\=/% > local.properties
)

echo SDK : %ANDROID_HOME%
echo Java: %JAVA_HOME%
if defined JAVA_HOME "%JAVA_HOME%\bin\java.exe" -version
echo.

echo Stopping old Gradle daemons (Java 25 needs Gradle 9)...
call "%~dp0gradlew.bat" --stop >nul 2>&1

echo Building debug APK...
call "%~dp0gradlew.bat" assembleDebug
if errorlevel 1 (
  echo.
  echo Gradle build failed.
  echo First-time builds download Gradle 9 and the Android plugin; keep this PC online.
  echo If Android Studio asks to install SDK Platform 36 (Android 16) or Build-Tools 36, accept it.
  echo Then: File ^> Open this folder, wait for sync, Build ^> Build APK^(s^).
  exit /b 1
)

if not exist "app\build\outputs\apk\debug\app-debug.apk" (
  echo APK was not created.
  exit /b 1
)

copy /Y "app\build\outputs\apk\debug\app-debug.apk" "SIMUST-2.3-debug.apk" >nul
copy /Y "app\build\outputs\apk\debug\app-debug.apk" "SIMUST-ZFlip6-2.3-debug.apk" >nul
copy /Y "app\build\outputs\apk\debug\app-debug.apk" "app\build\outputs\apk\debug\SIMUST-2.3-debug.apk" >nul
echo APK ready:
echo   %cd%\SIMUST-2.3-debug.apk
echo   %cd%\SIMUST-ZFlip6-2.3-debug.apk
echo   %cd%\app\build\outputs\apk\debug\app-debug.apk
echo   (same file; Gradle always names the build app-debug.apk)

echo.
echo Devices:
"%ANDROID_HOME%\platform-tools\adb.exe" start-server
"%ANDROID_HOME%\platform-tools\adb.exe" devices
"%ANDROID_HOME%\platform-tools\adb.exe" uninstall com.simust.playsmart
"%ANDROID_HOME%\platform-tools\adb.exe" install -r "app\build\outputs\apk\debug\app-debug.apk"
if errorlevel 1 exit /b 1

echo.
echo Installed. Open SIMUST on the Z Flip 6.
echo Operator URL: http://157.180.47.98/operator
echo Use the phone SIM or Wi-Fi. Leave Windows app.py running.
exit /b 0
