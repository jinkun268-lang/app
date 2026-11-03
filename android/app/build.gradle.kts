plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
}

val localDebugEnabled = providers.gradleProperty("citrusLocalDebug").orNull == "true"
// CI 通过 -P 注入版本号，保证版本单调递增；本地构建保留原默认值。
val appVersionCode = providers.gradleProperty("appVersionCode").orNull?.toIntOrNull() ?: 4
val appVersionName = providers.gradleProperty("appVersionName").orNull ?: "0.1.3"
// CI 通过环境变量提供签名证书；未提供时回退到 debug 签名（与历史安装包同一签名身份）。
val ciKeystorePath = System.getenv("CITRUS_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }

android {
    namespace = "com.example.citruscollect"
    compileSdk = 35
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "com.example.citruscollect"
        minSdk = 26
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersionName
        buildConfigField("String", "API_BASE_URL", "\"https://api.homemanager.com.cn/api/v1/\"")
        buildConfigField("boolean", "LOCAL_DEBUG", "false")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        if (ciKeystorePath != null) {
            create("ci") {
                storeFile = file(ciKeystorePath)
                storePassword = System.getenv("CITRUS_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("CITRUS_KEY_ALIAS")
                keyPassword = System.getenv("CITRUS_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        debug {
            if (localDebugEnabled) {
                applicationIdSuffix = ".local"
                versionNameSuffix = "-local"
                buildConfigField("String", "API_BASE_URL", "\"http://10.0.2.2:18081/api/v1/\"")
                buildConfigField("boolean", "LOCAL_DEBUG", "true")
                resValue("string", "app_name", "柚见·本地调试")
            }
        }
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("ci") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation("androidx.compose.material:material-icons-core")
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.navigation.compose)

    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)

    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)

    implementation(libs.androidx.datastore.preferences)
    implementation(libs.kotlinx.coroutines.android)

    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)

    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.core)
    androidTestImplementation("androidx.test:rules:1.6.1")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")
}
