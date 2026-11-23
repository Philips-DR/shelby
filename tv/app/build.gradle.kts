import com.android.build.api.variant.ApplicationAndroidComponentsExtension

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Where Shelby is, read at build time from the git-ignored tv/server.txt (one line, such as http://192.168.70.108:8750;
// the address of the laptop, which ./start-docker publishes the backend on when SHELBY_HOME_ADDRESS is set). Absent, the
// app uses 127.0.0.1, which is how the TV reaches the backend over ADB (`adb reverse`). The same address is the only one
// the app may speak plain http to (the generated network_security_config below), so a build refuses anything that is not
// a private home-network address: a public one in this file would send the token across the internet in the clear.
val serverUrl: String = rootProject.file("server.txt").let { file ->
    if (file.exists()) file.readText().trim() else "http://127.0.0.1:8750"
}
val serverHost: String = Regex("""http://(\d{1,3}(?:\.\d{1,3}){3}):\d{1,5}""").matchEntire(serverUrl)?.groupValues?.get(1)
    ?: throw GradleException("tv/server.txt must be one line such as http://192.168.70.108:8750 (http, an IPv4 address, a port); it says: $serverUrl")
run {
    val parts = serverHost.split(".").map { it.toInt() }
    val private = parts.all { it in 0..255 } && (parts[0] == 127 || parts[0] == 10 ||
        (parts[0] == 192 && parts[1] == 168) || (parts[0] == 172 && parts[1] in 16..31))
    if (!private) throw GradleException("tv/server.txt names $serverHost, which is not a private home-network address " +
        "(127.x, 10.x, 172.16-31.x or 192.168.x). The app sends its token in plain http, so it will not be built for that.")
}

// The rule that lets the app use plain http, written from the address above so the two cannot disagree. Android's
// resource compiler cannot take a variable, so Gradle writes the file. 127.0.0.1 stays, for development over ADB.
abstract class WriteNetworkConfig : DefaultTask() {
    @get:Input abstract val host: Property<String>
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction
    fun write() {
        val xml = outputDir.get().asFile.resolve("xml").apply { mkdirs() }
        val hosts = listOf("127.0.0.1", host.get()).distinct()
        xml.resolve("network_security_config.xml").writeText(
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n" +
            "<network-security-config>\n" +
            "    <!-- Written by the build from tv/server.txt. Plain http to these addresses and no others. -->\n" +
            "    <domain-config cleartextTrafficPermitted=\"true\">\n" +
            hosts.joinToString("") { "        <domain includeSubdomains=\"false\">$it</domain>\n" } +
            "    </domain-config>\n" +
            "</network-security-config>\n"
        )
    }
}

val writeNetworkConfig = tasks.register<WriteNetworkConfig>("writeNetworkConfig") {
    host.set(serverHost)
    outputDir.set(layout.buildDirectory.dir("generated/shelby/res"))
}

extensions.getByType<ApplicationAndroidComponentsExtension>().onVariants { variant ->
    variant.sources.res?.addGeneratedSourceDirectory(writeNetworkConfig, WriteNetworkConfig::outputDir)
}

android {
    namespace = "ai.ayadata.shelby.tv"
    compileSdkVersion("android-37.2")

    defaultConfig {
        applicationId = "ai.ayadata.shelby.tv"
        minSdk = 31
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"
        ndk {
            abiFilters += "armeabi-v7a"
        }
        val tokenFile = rootProject.file("token.txt")
        val token = if (tokenFile.exists()) tokenFile.readText().trim() else ""
        buildConfigField("String", "API_TOKEN", "\"$token\"")
        buildConfigField("String", "SHELBY_URL", "\"$serverUrl\"")
    }

    buildTypes {
        release {
            // The build that goes on the TV. A debug build is several times slower under Compose, so
            // speed is only ever judged on this one. Signed with the debug key: it is sideloaded to
            // one TV, and a new APK installs over the old one only if the key is the same.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        jvmToolchain(17)
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.11.01")
    implementation(composeBom)
    implementation("androidx.tv:tv-foundation:1.0.0")
    implementation("androidx.tv:tv-material:1.1.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("com.squareup.okhttp3:okhttp:5.5.1")
    // The player. It streams over HTTP with byte ranges, so nothing is downloaded whole.
    implementation("androidx.media3:media3-exoplayer:1.11.1")
    // The media session: the foreground service, the remote's media keys while another app is in front, the notification.
    implementation("androidx.media3:media3-session:1.11.1")

    testImplementation("junit:junit:4.13.2")
    // The real org.json, for tests: on the phone it is Android's own, which a plain JVM test does not have.
    testImplementation("org.json:json:20240303")
}
