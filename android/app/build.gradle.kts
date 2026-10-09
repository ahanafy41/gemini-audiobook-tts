plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.antigravity.audiobook"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.antigravity.audiobook"
        minSdk = 26
        targetSdk = 34
        versionCode = 14
        versionName = "1.1.7"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    val findKeystore = {
        val f1 = file("${project.rootDir}/keystore/permanent.keystore")
        val f2 = file("${project.rootDir}/android/keystore/permanent.keystore")
        if (f1.exists()) f1 else if (f2.exists()) f2 else null
    }

    signingConfigs {
        create("permanentSign") {
            val ksFile = findKeystore()
            if (ksFile != null && ksFile.exists()) {
                storeFile = ksFile
                storePassword = "geminiAudiobook2026"
                keyAlias = "audiobook_key"
                keyPassword = "geminiAudiobook2026"
            }
        }
    }

    buildTypes {
        debug {
            val ksFile = findKeystore()
            if (ksFile != null && ksFile.exists()) {
                signingConfig = signingConfigs.getByName("permanentSign")
            }
        }
        release {
            isMinifyEnabled = false
            val ksFile = findKeystore()
            if (ksFile != null && ksFile.exists()) {
                signingConfig = signingConfigs.getByName("permanentSign")
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
            excludes += "**/*.md"
            excludes += "**/project_spec.json"
            excludes += "**/tasks.md"
            excludes += "**/debug_manifest.json"
            excludes += "**/references_manifest.json"
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // Media3 & ExoPlayer for Accessible Audio Playback
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-session:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")

    // Networking for Gemini API
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // Kotlin Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // Encrypted Storage for BYOK API Key
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
}
