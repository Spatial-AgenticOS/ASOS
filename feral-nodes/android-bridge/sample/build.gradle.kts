plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ai.feral.app"
    compileSdk = 34

    defaultConfig {
        // Promoted from "ai.feral.sample" → "ai.feral.app" in 2026.5.8
        // when this app became the canonical FERAL Android app of
        // record (replacing the deleted apps/android/ and the
        // never-published feral-nodes/android-app/). See
        // CHANGELOG.md and feral-nodes/V2_MOBILE_PORTING.md.
        applicationId = "ai.feral.app"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
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
    implementation(project(":bridge"))
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
}
