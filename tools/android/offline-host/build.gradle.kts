/*
 * keel offline host: the WebView activity, JS bridge and Play Billing shared by the
 * studio's offline apps. An app includes this folder as the Gradle project
 * ":offline-host" (see README.md) and its MainActivity extends OfflineWebActivity.
 * Build output goes under the consuming app's build folder, never into keel-base.
 */
plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

layout.buildDirectory.set(rootProject.layout.buildDirectory.dir("offline-host"))

android {
    namespace = "keel.offlinehost"
    compileSdk = 36

    defaultConfig {
        minSdk = 26
        consumerProguardFiles("consumer-rules.pro")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    api("androidx.core:core-ktx:1.16.0")
    api("androidx.activity:activity-ktx:1.10.1")
    api("androidx.core:core-splashscreen:1.0.1")
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.browser:browser:1.9.0")
    implementation("com.android.billingclient:billing-ktx:8.0.0")
    implementation("com.google.android.play:review-ktx:2.0.2")
    testImplementation("junit:junit:4.13.2")
}
