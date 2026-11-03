import java.net.URI
import java.util.Properties
import java.util.zip.ZipFile

plugins {
  alias(libs.plugins.android.application)
  alias(libs.plugins.compose.compiler)
  alias(libs.plugins.kotlin.serialization)
}

val secretsFile = rootProject.file("secrets.properties")
val secrets = Properties()
if (secretsFile.exists()) {
    secrets.load(secretsFile.inputStream())
}

android {
  namespace = "com.damirl.ray"
  compileSdk = 36

  defaultConfig {
    applicationId = "com.damirl.ray"
    minSdk = 28
    targetSdk = 35
    versionCode = 1
    versionName = "1.0"

    // 64-bit ARM phones only: Vosk's native libraries for every other CPU added ~30 MB
    ndk { abiFilters += "arm64-v8a" }

    val lanUrl = secrets.getProperty("STRATA_LAN_URL", "http://192.168.1.100:8080")
    val remoteUrl = secrets.getProperty("STRATA_REMOTE_URL", "https://your-server.example.com")
    val apiKey = secrets.getProperty("STRATA_API_KEY", "")

    buildConfigField("String", "STRATA_LAN_URL", "\"$lanUrl\"")
    buildConfigField("String", "STRATA_REMOTE_URL", "\"$remoteUrl\"")
    buildConfigField("String", "STRATA_API_KEY", "\"$apiKey\"")
  }

  buildTypes {
    release {
      isMinifyEnabled = false
      proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
    }
  }
  compileOptions {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
  }
  buildFeatures {
    compose = true
    aidl = false
    buildConfig = true
    shaders = false
  }

  packaging {
    resources {
      excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
  }

  testOptions {
    unitTests.isReturnDefaultValues = true
  }

  // ./gradlew lintDebug: the findings that existed on 2026-11-03 are in lint-baseline.xml; new ones are reported
  lint {
    baseline = file("lint-baseline.xml")
    abortOnError = false
    checkDependencies = false
  }
}

kotlin {
  jvmToolchain(17)
}

// Ray's animated panda in the voice drawer is the web app's own drawing code: serve/web/rayface.js is copied into the
// app's assets at build time (assets/rayface/, next to src/main/assets/rayface/index.html), so there is one source
abstract class CopyRayFace : DefaultTask() {
  @get:InputFile abstract val script: RegularFileProperty
  @get:OutputDirectory abstract val outputDir: DirectoryProperty

  @TaskAction
  fun copy() {
    val dir = outputDir.get().asFile.resolve("rayface")
    dir.mkdirs()
    script.get().asFile.copyTo(dir.resolve("rayface.js"), overwrite = true)
  }
}

val copyRayFace = tasks.register<CopyRayFace>("copyRayFace") {
  script.set(rootProject.file("../serve/web/rayface.js"))
}

// The "Ok Ray" wake word's Vosk model (small English, ~40 MB): downloaded once into android/.vosk-cache (git-ignored)
// and bundled into assets/vosk-model/ with a version file, which HotwordListenerService unpacks on first use
abstract class DownloadVoskModel : DefaultTask() {
  @get:Input abstract val url: Property<String>
  @get:Input abstract val modelName: Property<String>
  @get:Internal abstract val cacheDir: DirectoryProperty
  @get:OutputDirectory abstract val outputDir: DirectoryProperty

  @TaskAction
  fun fetch() {
    val cache = cacheDir.get().asFile.apply { mkdirs() }
    val zip = cache.resolve("${modelName.get()}.zip")
    if (!zip.exists() || zip.length() < 1_000_000) {
      logger.lifecycle("Downloading the Vosk model ${modelName.get()}")
      val part = cache.resolve("${modelName.get()}.zip.part")
      URI(url.get()).toURL().openStream().use { input -> part.outputStream().use { input.copyTo(it) } }
      part.renameTo(zip)
    }
    val out = outputDir.get().asFile.resolve("vosk-model")
    out.deleteRecursively()
    out.mkdirs()
    ZipFile(zip).use { z ->
      for (e in z.entries().asSequence()) {
        val rel = e.name.substringAfter('/', "")                      // drop the zip's top folder
        if (rel.isEmpty() || rel.contains("..")) continue
        val f = out.resolve(rel)
        if (e.isDirectory) {
          f.mkdirs()
        } else {
          f.parentFile.mkdirs()
          z.getInputStream(e).use { input -> f.outputStream().use { input.copyTo(it) } }
        }
      }
    }
    out.resolve("VERSION").writeText(modelName.get())
  }
}

val downloadVoskModel = tasks.register<DownloadVoskModel>("downloadVoskModel") {
  modelName.set("vosk-model-small-en-us-0.15")
  url.set("https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip")
  cacheDir.set(rootProject.layout.projectDirectory.dir(".vosk-cache"))
}

androidComponents {
  onVariants { variant ->
    variant.sources.assets?.addGeneratedSourceDirectory(copyRayFace, CopyRayFace::outputDir)
    variant.sources.assets?.addGeneratedSourceDirectory(downloadVoskModel, DownloadVoskModel::outputDir)
  }
}

dependencies {
  val composeBom = platform(libs.androidx.compose.bom)
  implementation(composeBom)
  androidTestImplementation(composeBom)

  // Core Android dependencies
  implementation(libs.androidx.core.ktx)
  implementation(libs.androidx.lifecycle.runtime.ktx)
  implementation(libs.androidx.activity.compose)

  // Arch Components
  implementation(libs.androidx.lifecycle.runtime.compose)
  implementation(libs.androidx.lifecycle.viewmodel.compose)

  // Compose
  implementation(libs.androidx.compose.ui)
  implementation(libs.androidx.compose.ui.tooling.preview)
  implementation(libs.androidx.compose.material3)
  // Material icons extended
  implementation(libs.androidx.compose.material.icons.extended)

  // MediaSessionCompat & MediaButton support
  implementation(libs.androidx.media)

  // Networking (OkHttp + SSE + JSON)
  implementation(libs.okhttp)
  implementation(libs.okhttp.sse)
  implementation(libs.kotlinx.serialization.json)

  // "Ok Ray" wake word: Vosk, offline, with its small English model (see downloadVoskModel)
  implementation(libs.vosk.android) { exclude(group = "net.java.dev.jna") }
  implementation(libs.jna) { artifact { type = "aar" } }

  // Tooling
  debugImplementation(libs.androidx.compose.ui.tooling)
  // Instrumented tests
  androidTestImplementation(libs.androidx.compose.ui.test.junit4)
  debugImplementation(libs.androidx.compose.ui.test.manifest)

  // Local tests: jUnit, coroutines, Android runner
  testImplementation(libs.junit)
  testImplementation(libs.kotlinx.coroutines.test)
  testImplementation("org.json:json:20240303")

  // Instrumented tests: jUnit rules and runners
  androidTestImplementation(libs.androidx.test.core)
  androidTestImplementation(libs.androidx.test.ext.junit)
  androidTestImplementation(libs.androidx.test.runner)
  androidTestImplementation(libs.androidx.test.espresso.core)

  // Navigation
  implementation(libs.androidx.navigation3.ui)
  implementation(libs.androidx.navigation3.runtime)
  implementation(libs.androidx.lifecycle.viewmodel.navigation3)
}
