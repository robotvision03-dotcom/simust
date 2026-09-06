plugins {
    id("com.android.application")
}

android {
    namespace = "com.simust.playsmart"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.simust.playsmart"
        minSdk = 24
        targetSdk = 36
        versionCode = 5
        versionName = "2.3"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
}

afterEvaluate {
    tasks.named("assembleDebug").configure {
        doLast {
            val src = layout.buildDirectory.file("outputs/apk/debug/app-debug.apk").get().asFile
            if (!src.exists()) return@doLast
            val named = "SIMUST-${android.defaultConfig.versionName}-debug.apk"
            src.copyTo(src.resolveSibling(named), overwrite = true)
            src.copyTo(rootProject.projectDir.resolve(named), overwrite = true)
            src.copyTo(rootProject.projectDir.resolve("SIMUST-ZFlip6-2.3-debug.apk"), overwrite = true)
        }
    }
}
