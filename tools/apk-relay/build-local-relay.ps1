param(
    [string]$DecodedRoot = (Join-Path $PSScriptRoot '..\..\build\original-relay-apk'),
    [string]$OutputApk = (Join-Path $PSScriptRoot '..\..\build\local-relay-v3.apk')
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$decoded = (Resolve-Path -LiteralPath $DecodedRoot).Path
$buildRoot = Join-Path $repoRoot 'build'
$relaySrc = Join-Path $PSScriptRoot 'src'
$relayClasses = Join-Path $buildRoot 'relay-classes'
$relayDex = Join-Path $buildRoot 'relay-dex'
$unsigned = Join-Path $buildRoot 'local-relay-v3-unsigned.apk'
$aligned = Join-Path $buildRoot 'local-relay-v3-aligned-unsigned.apk'
$androidJar = Join-Path $repoRoot '.tools\android-platform-35\android.jar'
$d8Jar = Join-Path $repoRoot '.tools\android-build-tools\extracted\android-15\lib\d8.jar'
$zipalign = Join-Path $repoRoot '.tools\android-build-tools\extracted\android-15\zipalign.exe'
$apksigner = Join-Path $repoRoot '.tools\android-build-tools\extracted\android-15\apksigner.bat'
$apktool = Join-Path $repoRoot 'apktool.jar'
$keystore = Join-Path $buildRoot 'local-sdk-test.keystore'
$activity = Join-Path $decoded 'smali\com\idoltimex\sdkbase\UnityPlayerActivity.smali'
$sdkDomain = Join-Path $decoded 'smali\com\charles\weblib\network\SdkDomainManager.smali'

if (!(Test-Path -LiteralPath $keystore)) {
    Write-Output "generating signing keystore: $keystore"
    & keytool -genkeypair -v -keystore $keystore -storepass local-sdk-test -keypass local-sdk-test `
        -alias local-sdk-test -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=local-sdk-test, OU=dev, O=local, L=local, S=local, C=CN"
    if ($LASTEXITCODE -ne 0) { throw "keytool failed with exit code $LASTEXITCODE" }
}

foreach ($required in @($androidJar, $d8Jar, $zipalign, $apksigner, $apktool, $keystore, $activity, $sdkDomain)) {
    if (!(Test-Path -LiteralPath $required)) {
        throw "required build input is missing: $required"
    }
}

New-Item -ItemType Directory -Force -Path $relayClasses, $relayDex | Out-Null
Get-ChildItem -LiteralPath $relayClasses -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $relayDex -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'patch-sdk-domains.ps1') -SdkDomainSmali $sdkDomain
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'patch-unity-player-activity.ps1') -ActivitySmali $activity
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'patch-sdk-floating.ps1') -DecodedRoot $decoded

$javaFiles = Get-ChildItem -LiteralPath $relaySrc -Recurse -Filter '*.java' -File | ForEach-Object FullName
& javac -source 8 -target 8 -Xlint:-options -cp $androidJar -d $relayClasses $javaFiles
if ($LASTEXITCODE -ne 0) { throw "javac failed with exit code $LASTEXITCODE" }

$relayJar = Join-Path $relayDex 'relay-classes.jar'
& jar cf $relayJar -C $relayClasses .
if ($LASTEXITCODE -ne 0) { throw "failed to package relay classes" }
& java -cp $d8Jar com.android.tools.r8.D8 --lib $androidJar --min-api 23 --output $relayDex $relayJar
if ($LASTEXITCODE -ne 0) { throw "d8 failed with exit code $LASTEXITCODE" }

Copy-Item -Force (Join-Path $relayDex 'classes.dex') (Join-Path $relayDex 'classes3.dex')
& java -jar $apktool b $decoded -o $unsigned --use-aapt2
if ($LASTEXITCODE -ne 0) { throw "apktool build failed with exit code $LASTEXITCODE" }

$sevenZip = (Get-Command 7z.exe).Source
Push-Location $relayDex
try {
    & $sevenZip u -tzip $unsigned classes3.dex -mx=0
    if ($LASTEXITCODE -ne 0) { throw "failed to add classes3.dex" }
}
finally {
    Pop-Location
}

& $zipalign -f 4 $unsigned $aligned
if ($LASTEXITCODE -ne 0) { throw "zipalign failed with exit code $LASTEXITCODE" }
& $apksigner sign --ks $keystore --ks-key-alias local-sdk-test --ks-pass pass:local-sdk-test --key-pass pass:local-sdk-test --out $OutputApk $aligned
if ($LASTEXITCODE -ne 0) { throw "apksigner failed with exit code $LASTEXITCODE" }
& $apksigner verify --verbose $OutputApk
if ($LASTEXITCODE -ne 0) { throw "APK signature verification failed" }

if ([IO.Path]::GetFileName($OutputApk) -eq 'local-relay-v3.apk') {
    $displayName = ([char]0x6843) + '-local-relay-v3.apk'
    Copy-Item -Force $OutputApk (Join-Path $buildRoot $displayName)
}
Write-Output "built: $OutputApk"
