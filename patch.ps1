# One-click patch + export: turn a user-supplied original APK into the signed
# local-relay v3 APK. The project never ships or references a bundled original
# APK, so the input path must be provided manually (parameter or prompt).
param(
    [string]$Apk = '',
    [switch]$Clean,
    [string]$OutputDir = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$buildRoot = Join-Path $repoRoot 'build'
$decoded = Join-Path $buildRoot 'original-relay-apk'
$relayTool = Join-Path $repoRoot 'tools\apk-relay'
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $distDir = Join-Path $repoRoot 'dist'
} else {
    $distDir = $OutputDir
}

function Require-Command([string]$name) {
    if (!(Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "required tool not found on PATH: $name"
    }
}

function Require-File([string]$path, [string]$description) {
    if (!(Test-Path -LiteralPath $path)) {
        throw "required $description is missing: $path"
    }
}

# 1. Manual input of the original APK (never assumed from the workspace).
if ([string]::IsNullOrWhiteSpace($Apk)) {
    $Apk = Read-Host 'Enter the path to the original APK (you may drag the file here)'
}
if ([string]::IsNullOrWhiteSpace($Apk)) {
    throw 'no original APK path was provided'
}
$Apk = $Apk.Trim().Trim('"')
if (!(Test-Path -LiteralPath $Apk -PathType Leaf)) {
    throw "APK file does not exist: $Apk"
}
$apkFull = (Resolve-Path -LiteralPath $Apk).Path

$magic = [IO.File]::ReadAllBytes($apkFull)[0..3]
if ($magic.Count -lt 4 -or $magic[0] -ne 0x50 -or $magic[1] -ne 0x4B) {
    throw "not a valid APK/ZIP file (missing PK header): $apkFull"
}

# 2. Verify the build toolchain.
$apktool = Join-Path $repoRoot 'apktool.jar'
$androidJar = Join-Path $repoRoot '.tools\android-platform-35\android.jar'
$d8Jar = Join-Path $repoRoot '.tools\android-build-tools\extracted\android-15\lib\d8.jar'
$zipalign = Join-Path $repoRoot '.tools\android-build-tools\extracted\android-15\zipalign.exe'
$apksigner = Join-Path $repoRoot '.tools\android-build-tools\extracted\android-15\apksigner.bat'
foreach ($f in @($apktool, $androidJar, $d8Jar, $zipalign, $apksigner)) {
    Require-File $f 'build input'
}
foreach ($c in @('java', 'javac', 'jar', 'keytool', '7z')) {
    Require-Command $c
}

# 3. Decode the original APK when missing or when a clean rebuild is requested.
$apktoolYml = Join-Path $decoded 'apktool.yml'
if ($Clean -or !(Test-Path -LiteralPath $apktoolYml)) {
    Write-Output "decoding original APK (this can take a few minutes)..."
    if (Test-Path -LiteralPath $decoded) {
        Remove-Item -LiteralPath $decoded -Recurse -Force
    }
    & java -jar $apktool d -f -o $decoded $apkFull
    if ($LASTEXITCODE -ne 0) { throw "apktool decode failed with exit code $LASTEXITCODE" }
} else {
    Write-Output "reusing existing decoded tree: $decoded"
}

# 4. Apply patches, compile the relay dex, rebuild, zipalign, and sign.
$outApk = Join-Path $buildRoot 'local-relay-v3.apk'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $relayTool 'build-local-relay.ps1') -DecodedRoot $decoded -OutputApk $outApk

# 5. Export the signed APK and its SHA-256 to the output directory.
New-Item -ItemType Directory -Force -Path $distDir | Out-Null
$exportName = ([char]0x6843) + '-local-relay-v3.apk'
$exportPath = Join-Path $distDir $exportName
Copy-Item -Force $outApk $exportPath
$hash = (Get-FileHash -LiteralPath $exportPath -Algorithm SHA256).Hash
Set-Content -LiteralPath ($exportPath + '.sha256') -Value $hash -Encoding ascii

Write-Output "exported: $exportPath"
Write-Output "SHA-256: $hash"
