param(
    [Parameter(Mandatory = $true)]
    [string]$DecodedRoot
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $DecodedRoot).Path

function Update-Smali([string]$path, [string]$marker, [string]$old, [string]$new, [string]$description) {
    $resolved = (Resolve-Path -LiteralPath $path).Path
    $text = [IO.File]::ReadAllText($resolved)
    $lineEnding = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $old = [regex]::Replace($old, "`r?`n", $lineEnding)
    $new = [regex]::Replace($new, "`r?`n", $lineEnding)
    if ($text.Contains($marker)) {
        Write-Output "already patched ${description}: ${resolved}"
        return
    }
    if (!$text.Contains($old)) {
        throw "smali anchor not found for ${description}: ${resolved}"
    }
    $text = $text.Replace($old, $new)
    [IO.File]::WriteAllText($resolved, $text, [Text.UTF8Encoding]::new($false))
    Write-Output "patched ${description}: ${resolved}"
}

$sdk = Join-Path $root 'smali\com\idoltimex\lib18game\EighteenGameSDK.smali'
$sdkCallback = Join-Path $root 'smali\com\idoltimex\lib18game\EighteenGameSDK$2.smali'
$floating = Join-Path $root 'smali\com\charles\weblib\sdk\api\GameSdkFloating.smali'
$menu = Join-Path $root 'smali\com\charles\weblib\sdk\api\GameSdkFloating$show$runnable$1$1$2.smali'

$onCreateOld = @'
    invoke-super {p0, p1}, Lcom/idoltimex/sdkbase/sdk/SdkVirtualClass;->onCreate(Landroid/app/Activity;)V

    .line 86
    invoke-direct {p0, p1}, Lcom/idoltimex/lib18game/EighteenGameSDK;->readTestEnvFromManifest(Landroid/app/Activity;)Z

    move-result v0

    if-eqz v0, :cond_0

    const-string v1, "696df059ee575"

    goto :goto_0

    :cond_0
    const-string v1, "693bd69250b4b"

    .line 87
    :goto_0
    iput-object v1, p0, Lcom/idoltimex/lib18game/EighteenGameSDK;->game_key:Ljava/lang/String;

    .line 88
    invoke-direct {p0, p1, v0}, Lcom/idoltimex/lib18game/EighteenGameSDK;->ensureSdkInitialized(Landroid/app/Activity;Z)V

    return-void
'@
$onCreateNew = @'
    invoke-super {p0, p1}, Lcom/idoltimex/sdkbase/sdk/SdkVirtualClass;->onCreate(Landroid/app/Activity;)V

    # localrelay: request SDK floating window at game startup
    const/4 v0, 0x1
    iput-boolean v0, p0, Lcom/idoltimex/lib18game/EighteenGameSDK;->floatRequested:Z
    invoke-static {v0}, Lcom/charles/weblib/sdk/api/GameSdkFloating;->setIdleHalfHideEnabled(Z)V

    .line 86
    invoke-direct {p0, p1}, Lcom/idoltimex/lib18game/EighteenGameSDK;->readTestEnvFromManifest(Landroid/app/Activity;)Z

    move-result v0

    if-eqz v0, :cond_0

    const-string v1, "696df059ee575"

    goto :goto_0

    :cond_0
    const-string v1, "693bd69250b4b"

    .line 87
    :goto_0
    iput-object v1, p0, Lcom/idoltimex/lib18game/EighteenGameSDK;->game_key:Ljava/lang/String;

    .line 88
    invoke-direct {p0, p1, v0}, Lcom/idoltimex/lib18game/EighteenGameSDK;->ensureSdkInitialized(Landroid/app/Activity;Z)V

    # localrelay: show immediately when initialization was already complete
    invoke-static {}, Lcom/charles/weblib/sdk/GameSdkInitializer;->isInitialized()Z
    move-result v0
    if-eqz v0, :cond_localrelay_float_pending
    iget-object v0, p0, Lcom/idoltimex/lib18game/EighteenGameSDK;->mActivity:Landroid/app/Activity;
    invoke-static {v0}, Lcom/charles/weblib/sdk/GameSdkManager;->showFloatingButton(Landroid/app/Activity;)V
    :cond_localrelay_float_pending

    return-void
'@
Update-Smali $sdk '# localrelay: request SDK floating window at game startup' $onCreateOld $onCreateNew 'SDK startup floating request'

$onResumeOld = @'
    invoke-static {}, Lcom/charles/weblib/sdk/GameSdkInitializer;->isInitialized()Z

    move-result v0

    if-eqz v0, :cond_0

    invoke-static {}, Lcom/charles/weblib/sdk/GameSdkManager;->isLoggedIn()Z

    move-result v0

    if-eqz v0, :cond_0

    .line 263
'@
$onResumeNew = @'
    invoke-static {}, Lcom/charles/weblib/sdk/GameSdkInitializer;->isInitialized()Z

    move-result v0

    if-eqz v0, :cond_0

    # localrelay: allow the SDK menu before login so Relay is available at startup
    .line 263
'@
Update-Smali $sdk '# localrelay: allow the SDK menu before login so Relay is available at startup' $onResumeOld $onResumeNew 'SDK pre-login floating display'

$callbackOld = @'
    invoke-static {v0, p1}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I

    return-void
'@
$callbackNew = @'
    invoke-static {v0, p1}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I

    # localrelay: show SDK floating window after async initialization callback
    iget-object v0, p0, Lcom/idoltimex/lib18game/EighteenGameSDK$2;->this$0:Lcom/idoltimex/lib18game/EighteenGameSDK;
    const/4 v1, 0x1
    invoke-static {v0, v1}, Lcom/idoltimex/lib18game/EighteenGameSDK;->access$902(Lcom/idoltimex/lib18game/EighteenGameSDK;Z)Z
    move-result v2
    invoke-static {v1}, Lcom/charles/weblib/sdk/api/GameSdkFloating;->setIdleHalfHideEnabled(Z)V
    invoke-static {v0}, Lcom/idoltimex/lib18game/EighteenGameSDK;->access$2400(Lcom/idoltimex/lib18game/EighteenGameSDK;)Landroid/app/Activity;
    move-result-object v0
    invoke-static {v0}, Lcom/charles/weblib/sdk/GameSdkManager;->showFloatingButton(Landroid/app/Activity;)V

    return-void
'@
Update-Smali $sdkCallback '# localrelay: show SDK floating window after async initialization callback' $callbackOld $callbackNew 'async SDK startup floating display'

$halfHideOld = @'
    const/4 p3, 0x0

    .line 526
    invoke-virtual {p0, p3}, Lcom/charles/weblib/floating/assist/helper/FxAppHelper$Builder;->setEnableHalfHide(Z)Ljava/lang/Object;
'@
$halfHideNew = @'
    # localrelay: enable SDK edge half-hide
    const/4 p3, 0x1

    .line 526
    invoke-virtual {p0, p3}, Lcom/charles/weblib/floating/assist/helper/FxAppHelper$Builder;->setEnableHalfHide(Z)Ljava/lang/Object;
'@
Update-Smali $floating '# localrelay: enable SDK edge half-hide' $halfHideOld $halfHideNew 'SDK floating half-hide'

$menuOld = @'
    invoke-virtual {p1, v0, v2}, Lcom/charles/weblib/floating/view/FxViewHolder;->setOnClickListener(ILandroid/view/View$OnClickListener;)Lcom/charles/weblib/floating/view/FxViewHolder;

    return-void
'@
$menuNew = @'
    invoke-virtual {p1, v0, v2}, Lcom/charles/weblib/floating/view/FxViewHolder;->setOnClickListener(ILandroid/view/View$OnClickListener;)Lcom/charles/weblib/floating/view/FxViewHolder;

    # localrelay: add Relay configuration action to both SDK menu sides
    iget-object v0, p0, Lcom/charles/weblib/sdk/api/GameSdkFloating$show$runnable$1$1$2;->$activity:Landroid/app/Activity;
    invoke-static {p1, v0}, Lcom/idoltimex/localrelay/RelaySdkBridge;->install(Ljava/lang/Object;Landroid/app/Activity;)V

    return-void
'@
Update-Smali $menu '# localrelay: add Relay configuration action to both SDK menu sides' $menuOld $menuNew 'SDK Relay menu action'
