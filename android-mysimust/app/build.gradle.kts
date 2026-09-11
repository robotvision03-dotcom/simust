plugins {
    id("com.android.application")
}

import java.util.Properties

android {
    namespace = "com.simust.mysimust"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.simust.mysimust"
        minSdk = 24
        targetSdk = 36
        // Bump both for every Play upload.
        versionCode = 3
        versionName = "1.2"
        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    signingConfigs {
        create("release") {
            val propsFile = rootProject.file("keystore.properties")
            if (propsFile.exists()) {
                val props = Properties()
                propsFile.inputStream().use { props.load(it) }
                storeFile = rootProject.file(props.getProperty("storeFile"))
                storePassword = props.getProperty("storePassword")
                keyAlias = props.getProperty("keyAlias")
                keyPassword = props.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
            manifestPlaceholders["usesCleartextTraffic"] = "true"
            // Debug network config allows lab HTTP.
            // (Merged via androidResources / source set below.)
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            manifestPlaceholders["usesCleartextTraffic"] = "false"
            val releaseSigning = signingConfigs.findByName("release")
            if (releaseSigning != null && releaseSigning.storeFile != null && releaseSigning.storeFile!!.exists()) {
                signingConfig = releaseSigning
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        getByName("debug") {
            res.srcDir("src/debug/res")
        }
    }

    bundle {
        language { enableSplit = false }
        density { enableSplit = true }
        abi { enableSplit = true }
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
            val named = "MySIMUST-${android.defaultConfig.versionName}-debug.apk"
            src.copyTo(src.resolveSibling(named), overwrite = true)
            src.copyTo(rootProject.projectDir.resolve(named), overwrite = true)
            val phone = "MySIMUST-phone-tablet-${android.defaultConfig.versionName}-debug.apk"
            src.copyTo(rootProject.projectDir.resolve(phone), overwrite = true)
        }
    }
    tasks.named("bundleRelease").configure {
        doLast {
            val src = layout.buildDirectory
                .file("outputs/bundle/release/app-release.aab")
                .get()
                .asFile
            if (!src.exists()) return@doLast
            val named = "MySIMUST-${android.defaultConfig.versionName}-release.aab"
            src.copyTo(rootProject.projectDir.resolve(named), overwrite = true)
            println("Play upload bundle: ${rootProject.projectDir.resolve(named)}")
        }
    }
}
