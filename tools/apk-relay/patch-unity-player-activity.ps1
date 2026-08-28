param(
    [Parameter(Mandatory = $true)]
    [string]$ActivitySmali
)

$path = (Resolve-Path -LiteralPath $ActivitySmali).Path
$text = [IO.File]::ReadAllText($path)

$resumeOld = @'
    invoke-virtual {v0}, Lcom/unity3d/player/UnityPlayer;->onResume()V

    return-void
'@
$resumeNew = @'
    invoke-virtual {v0}, Lcom/unity3d/player/UnityPlayer;->onResume()V

    invoke-static {p0}, Lcom/idoltimex/localrelay/RelayController;->ensureStarted(Landroid/content/Context;)V

    return-void
'@

$startOld = @'
    invoke-virtual {v0}, Lcom/unity3d/player/UnityPlayer;->onStart()V

    return-void
'@
$startNew = @'
    invoke-virtual {v0}, Lcom/unity3d/player/UnityPlayer;->onStart()V

    invoke-static {p0}, Lcom/idoltimex/localrelay/RelayController;->ensureStarted(Landroid/content/Context;)V

    return-void
'@

if ($text.Contains('RelayController;->ensureStarted')) {
    Write-Output "already patched: $path"
    exit 0
}
if (!$text.Contains($resumeOld) -or !$text.Contains($startOld)) {
    throw "UnityPlayerActivity lifecycle anchors were not found: $path"
}

$text = $text.Replace($resumeOld, $resumeNew).Replace($startOld, $startNew)
[IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
Write-Output "patched lifecycle recovery: $path"
