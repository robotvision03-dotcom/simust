@echo off
set DIR=%~dp0
if exist "%DIR%gradle\wrapper\gradle-wrapper.jar" (
  java -jar "%DIR%gradle\wrapper\gradle-wrapper.jar" %*
) else (
  echo Open this folder in Android Studio to generate the Gradle wrapper, then Build APK.
  echo Project path: %DIR%
)
