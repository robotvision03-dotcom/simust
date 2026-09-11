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
  exit /b 1
)

if not exist "local.properties" (
  echo sdk.dir=%ANDROID_HOME:\=/% > local.properties
)

echo Building My SIMUST debug APK...
call "%~dp0gradlew.bat" assembleDebug
if errorlevel 1 exit /b 1

if not exist "app\build\outputs\apk\debug\app-debug.apk" (
  echo APK was not created.
  exit /b 1
)

echo.
echo Devices:
"%ANDROID_HOME%\platform-tools\adb.exe" start-server
"%ANDROID_HOME%\platform-tools\adb.exe" devices
"%ANDROID_HOME%\platform-tools\adb.exe" install -r "app\build\outputs\apk\debug\app-debug.apk"
if errorlevel 1 exit /b 1

echo.
echo Installed My SIMUST. Open the app and sign in at http://157.180.47.98/login
exit /b 0
