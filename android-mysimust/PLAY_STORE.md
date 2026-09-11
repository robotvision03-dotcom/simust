# Google Play — My SIMUST (`com.simust.mysimust`)
# ================================================
#
# You publish from Google Play Console in a browser. This repo prepares the
# signed Android App Bundle (.aab). Nobody can finish the upload without your
# Google account + one-time $25 Play Console registration.
#
# Package ID (immutable after first publish): com.simust.mysimust
# Current version for first upload: 1.2 (versionCode 3)
# Default host (release): https://my.simust.com
# Privacy policy URL (required): https://my.simust.com/privacy
#   (also http://157.180.47.98/privacy after VPS pull)
#
# ------------------------------------------------------------
# A. One-time setup
# ------------------------------------------------------------
# 1) Create a Play Console account:
#    https://play.google.com/console
#    Pay the developer registration fee and verify identity.
#
# 2) Create an upload keystore on this PC (once):
#      cd android-mysimust
#      .\create-upload-keystore.ps1
#    Back up mysimust-upload.jks + keystore.properties offline.
#    Losing them makes updates painful.
#
# 3) Deploy privacy policy to the live host (already in repo):
#      privacy_policy.html  →  /privacy on the VPS
#      .\deploy\update-all.ps1   (or update-vps.sh)
#    Confirm in a browser: https://my.simust.com/privacy
#
# 4) Ensure HTTPS works for my.simust.com (Caddy + DNS).
#    Release builds disallow cleartext HTTP.
#
# ------------------------------------------------------------
# B. Build the Play upload file
# ------------------------------------------------------------
#      cd android-mysimust
#      .\gradlew.bat clean bundleRelease
#
# Output:
#      android-mysimust\MySIMUST-1.2-release.aab
#      android-mysimust\app\build\outputs\bundle\release\app-release.aab
#
# ------------------------------------------------------------
# C. Create the Play Console app
# ------------------------------------------------------------
# 1) Play Console → Create app
#    - App name: My SIMUST
#    - Default language: English (or your primary language)
#    - App / Game: App
#    - Free / Paid: Free (in-app purchases via Stripe on web, not Play Billing)
#    - Declarations: accept policies
#
# 2) Dashboard → complete required tasks:
#    - App access (if login required: provide test username/password)
#    - Ads: No
#    - Content rating: fill IARC questionnaire (educational / sports training)
#    - Target audience: set age groups appropriately for academy players
#    - News app: No
#    - Data safety: see section E below
#    - Government apps: No
#    - Financial features: No (unless you declare Stripe payments as needed)
#    - Health: No
#
# 3) Store listing
#    Short description (~80 chars):
#      Sign in to My SIMUST — book sessions, track progress and results.
#    Full description: explain login, bookings, results, academy use.
#    App icon: 512×512 PNG (export from simust_logo / launcher art)
#    Feature graphic: 1024×500 PNG
#    Phone screenshots: at least 2 (login + dashboard)
#    7" / 10" tablet screenshots recommended (app supports tablets)
#    Privacy policy: https://my.simust.com/privacy
#
# 4) Production (or Internal testing first — recommended)
#    Create → Internal testing track → Create new release
#    Upload MySIMUST-1.2-release.aab
#    Enable Google Play App Signing when prompted (recommended)
#    Roll out to internal testers, then Production when ready
#
# ------------------------------------------------------------
# D. Every update later
# ------------------------------------------------------------
# 1) Bump versionCode (+1) and versionName in app/build.gradle.kts
# 2) Bump Prefs.APP_VERSION to match
# 3) .\gradlew.bat bundleRelease
# 4) Upload new .aab to a new release in Play Console
#
# ------------------------------------------------------------
# E. Data safety (typical answers for this WebView app)
# ------------------------------------------------------------
# Collected / shared:
#   - Account info (username, name) — collected by portal, processed on server
#   - App activity / training results — on server
#   - Approximate network info — for connectivity
# Not collected by the native shell: precise location, contacts, photos, mic
# Encryption in transit: Yes (HTTPS)
# Users can request deletion: via academy/admin (describe in policy)
#
# ------------------------------------------------------------
# F. Operator app (SIMUST / com.simust.playsmart)
# ------------------------------------------------------------
# Publish separately only if you want the lab operator console on Play.
# Same steps with android/ folder and a different package + listing.
# Most academies sideload the operator APK; players use My SIMUST on Play.
#
# ------------------------------------------------------------
# G. Assets folder
# ------------------------------------------------------------
# Put listing graphics in:
#   android-mysimust/play-store-assets/
# (icon-512.png, feature-1024x500.png, screenshots/)
