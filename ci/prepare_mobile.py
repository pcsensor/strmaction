"""Apply checked-in platform adapters to Flutter's pinned CI-generated runners.

No SDK is required to read or modify the client locally. The generated platform
projects and SDK tools live on CI runners only.
"""
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'client_flutter'
PLATFORM = CLIENT / 'platform'


def android():
    app = CLIENT / 'android/app'
    kotlin = app / 'src/main/kotlin/top/strmaction/companion'
    kotlin.mkdir(parents=True, exist_ok=True)
    for source in (PLATFORM / 'android').glob('*.kt'):
        shutil.copy2(source, kotlin / source.name)
    old = CLIENT / 'android/app/src/main/kotlin/top/strmaction/strmaction_desktop/MainActivity.kt'
    old.unlink(missing_ok=True)
    for name in ['PlaybackCache', 'PlaybackDiskCache', 'PlaybackPrefetcher', 'NetworkSpeedMeter']:
        shutil.copy2(ROOT / f'companion/app/src/main/java/top/strmaction/companion/{name}.kt', kotlin / f'{name}.kt')
    tests = app / 'src/test/kotlin/top/strmaction/companion'
    tests.mkdir(parents=True, exist_ok=True)
    for source in (PLATFORM / 'android/test').glob('*.kt'):
        shutil.copy2(source, tests / source.name)
    # Stable WebView 6.1.5 still uses the AGP 8 DSL. Pin the supported toolchain
    # instead of mutating dependencies in the pub cache.
    import re
    settings = CLIENT / 'android/settings.gradle.kts'
    text = re.sub(r'id\("com.android.application"\) version "[^"]+"', 'id("com.android.application") version "8.11.1"', settings.read_text())
    text = re.sub(r'id\("org.jetbrains.kotlin.android"\) version "[^"]+"', 'id("org.jetbrains.kotlin.android") version "2.2.20"', text)
    if 'id("org.jetbrains.kotlin.android")' not in text:
        text = text.replace('id("com.android.application") version "8.11.1" apply false', 'id("com.android.application") version "8.11.1" apply false\n    id("org.jetbrains.kotlin.android") version "2.2.20" apply false')
    settings.write_text(text)
    wrapper = CLIENT / 'android/gradle/wrapper/gradle-wrapper.properties'
    wrapper.write_text(re.sub(r'gradle-[0-9.]+-all.zip', 'gradle-8.14-all.zip', wrapper.read_text()))
    drawables = app / 'src/main/res/drawable'
    drawables.mkdir(parents=True, exist_ok=True)
    for name in ['ic_launcher.xml', 'banner.xml']:
        shutil.copy2(ROOT / 'companion/app/src/main/res/drawable' / name, drawables / name)
    gradle = app / 'build.gradle.kts'
    text = gradle.read_text().replace('top.strmaction.strmaction_desktop', 'top.strmaction.companion')
    if 'id("org.jetbrains.kotlin.android")' not in text:
        text = text.replace('id("com.android.application")', 'id("com.android.application")\n    id("org.jetbrains.kotlin.android")')
    text = text.replace('minSdk = flutter.minSdkVersion', 'minSdk = 24')
    # Never fall back to the debug identity for release builds.
    text = text.replace('signingConfig = signingConfigs.getByName("debug")', 'signingConfig = null')
    text += '''
android {
    buildFeatures { buildConfig = true }
    val releaseKey = System.getenv("STRMACTION_KEYSTORE_PATH")
    if (!releaseKey.isNullOrBlank()) {
        signingConfigs {
            create("releaseIdentity") {
                storeFile = file(releaseKey)
                storeType = "PKCS12"
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
        buildTypes { getByName("release") { signingConfig = signingConfigs.getByName("releaseIdentity") } }
    }
}
dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.4.1")
    implementation("androidx.media3:media3-exoplayer-dash:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")
    implementation("androidx.media3:media3-database:1.4.1")
    implementation("androidx.media3:media3-datasource-okhttp:1.4.1")
}
'''
    gradle.write_text(text)
    manifest = app / 'src/main/AndroidManifest.xml'
    text = manifest.read_text().replace('<application', '''
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <uses-permission android:name="android.permission.WAKE_LOCK" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />
    <uses-feature android:name="android.hardware.touchscreen" android:required="false" />
    <uses-feature android:name="android.software.leanback" android:required="false" />
    <application android:usesCleartextTraffic="true"''')
    text = text.replace('android:label="strmaction_desktop"', 'android:label="StrmAction" android:banner="@drawable/banner"').replace('@mipmap/ic_launcher', '@drawable/ic_launcher')
    text = text.replace('android:name=".MainActivity"', 'android:name="top.strmaction.companion.MainActivity" android:supportsPictureInPicture="true"')
    text = text.replace('<category android:name="android.intent.category.LAUNCHER"/>', '<category android:name="android.intent.category.LAUNCHER"/><category android:name="android.intent.category.LEANBACK_LAUNCHER"/>')
    text = text.replace('</application>', '<service android:name="top.strmaction.companion.PlaybackService" android:exported="false" android:foregroundServiceType="mediaPlayback" /></application>')
    manifest.write_text(text)


def ios():
    runner = CLIENT / 'ios/Runner'
    sources = runner / 'Native'
    shutil.copytree(ROOT / 'native/ios/Sources', sources, dirs_exist_ok=True)
    # Copy only the tested transport/decoder core; Flutter owns application UI.
    core = {'Model', 'Cache', 'Network'}
    player = {'PlaybackSession.swift', 'MediaTransport.swift', 'VideoPlayerAdapter.swift', 'PlayerDiagnostics.swift', 'SystemVolumeController.swift'}
    for path in sources.rglob('*.swift'):
        folder = path.relative_to(sources).parts[0]
        if folder in core or (folder == 'Trust' and path.name != 'TrustManagementView.swift') or (folder == 'Player' and path.name in player):
            continue
        path.unlink()
    for source in (PLATFORM / 'ios').glob('*.swift'):
        shutil.copy2(source, runner / source.name)
    shutil.copy2(ROOT / 'native/ios/Resources/ca/roots.pem', runner / 'roots.pem')
    shutil.copytree(ROOT / 'native/ios/Resources/Assets.xcassets/AppIcon.appiconset', runner / 'Assets.xcassets/AppIcon.appiconset', dirs_exist_ok=True)
    info = runner / 'Info.plist'
    data = plistlib.loads(info.read_bytes())
    data.update(CFBundleDisplayName='StrmAction', UIBackgroundModes=['audio'],
                NSAppTransportSecurity={'NSAllowsArbitraryLoads': True},
                NSLocalNetworkUsageDescription='连接家庭媒体服务器。',
                UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait', 'UIInterfaceOrientationLandscapeLeft', 'UIInterfaceOrientationLandscapeRight'])
    info.write_bytes(plistlib.dumps(data, sort_keys=False))
    podfile = CLIENT / 'ios/Podfile'
    if podfile.exists():
        import re
        text = re.sub(r"#?platform :ios, '[^']+'", "platform :ios, '16.0'", podfile.read_text())
        podfile.write_text(text)
    delegate = runner / 'AppDelegate.swift'
    text = delegate.read_text().replace('GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)',
        'GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)\n    UnifiedPlayerPlugin.register(with: engineBridge.pluginRegistry.registrar(forPlugin: "UnifiedPlayerPlugin")!)')
    if 'UnifiedPlayerPlugin.register' not in text:
        raise SystemExit('Flutter AppDelegate template changed; update native registration')
    delegate.write_text(text)
    subprocess.run(['ruby', str(ROOT / 'ci/prepare_ios.rb'), str(CLIENT / 'ios')], check=True)


if __name__ == '__main__':
    {'android': android, 'ios': ios}[sys.argv[1]]()
