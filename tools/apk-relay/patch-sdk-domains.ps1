param(
    [Parameter(Mandatory = $true)]
    [string]$SdkDomainSmali
)

$ErrorActionPreference = 'Stop'
$path = (Resolve-Path -LiteralPath $SdkDomainSmali).Path
$text = [IO.File]::ReadAllText($path)

$localUrl = 'http://127.0.0.1:8080'
$patchedField = 'BASE_HTTP_RELEASE_URL:Ljava/lang/String; = "' + $localUrl + '"'

# The five release base domains are unique to SdkDomainManager and each appears
# twice (a static field and a <clinit> const-string). A plain string replace per
# domain converges both occurrences to the loopback relay entry.
$domains = @(
    'https://bjyinhegame.com',
    'https://wangcaitt.com',
    'https://shouyek.com',
    'https://huochechushou.com',
    'https://tywhtg.com'
)

if ($text.Contains($patchedField)) {
    Write-Output "already patched: $path"
    exit 0
}

$missing = @()
foreach ($domain in $domains) {
    if (!$text.Contains($domain)) {
        $missing += $domain
    }
}
if ($missing.Count -gt 0) {
    throw "SdkDomainManager anchors not found for domains: $($missing -join ', ')"
}

foreach ($domain in $domains) {
    $text = $text.Replace($domain, $localUrl)
}
[IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
Write-Output "patched SDK domains: $path"
