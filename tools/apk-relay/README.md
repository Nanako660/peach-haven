# Local Relay APK

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

</div>

> **Category**: Implementation / Client Relay Patch Toolkit  
> **Status**: Confirmed  
> **Disclaimer**: This tool and documentation are for educational and security research purposes only.

This directory contains the tracked source and build scripts for the floating-window relay APK variant.

The relay exposes two loopback listeners inside the app:

- `127.0.0.1:8080` forwards to the account-management HTTP backend.
- `127.0.0.1:21001` forwards to the game TCP backend.

The right-top floating button edits both upstream addresses. Configuration is stored in the app's private `SharedPreferences` and never includes credentials in log output.

## One-click patch

The top-level [`patch.ps1`](../../patch.ps1) runs the full pipeline from a user-supplied original APK. It is not committed anywhere in this repository, so the input path must be provided manually:

```powershell
.\patch.ps1                       # interactive prompt for the original APK path
.\patch.ps1 -Apk ./original.apk
.\patch.ps1 -Clean -Apk ./original.apk   # force re-decode
```

The pipeline:

1. Decode the original APK into `build/original-relay-apk` (apktool).
2. `patch-sdk-domains.ps1` — rewrite the five release base domains in `SdkDomainManager.smali` to `http://127.0.0.1:8080`.
3. `patch-unity-player-activity.ps1` — inject lifecycle recovery into `UnityPlayerActivity`.
4. `patch-sdk-floating.ps1` — request the SDK floating window and add the Relay menu action.
5. Compile `src/` to `classes3.dex`, rebuild with apktool, inject the dex, zipalign, and sign.
6. Export the signed APK and its SHA-256 to `dist/`.

The signing keystore `build/local-sdk-test.keystore` is generated on first use and reused afterwards so that device installs keep their signature.

## Build scripts

- `build-local-relay.ps1` — the build stage (patches, dex, rebuild, sign). Called by `patch.ps1` after decoding.
- `patch-sdk-domains.ps1` — SDK base-domain convergence to the loopback relay entry.
- `patch-unity-player-activity.ps1` — lifecycle recovery patch.
- `patch-sdk-floating.ps1` — SDK floating-window and Relay menu patches.
- `patch-appconfig-urls.ps1` — **legacy** byte-level URL rewrite from the earlier SDK-URL variant; superseded by the smali `SdkDomainManager` rewrite and not used by the v3 relay pipeline.

## Logcat

Use these tags to follow the relay without mixing it with Unity or SDK logs:

```powershell
.tools/adb/adb.exe logcat -v threadtime -s LocalRelay:D LocalRelayOverlay:I LocalRelayConfig:I
```

The logs identify configuration, listener binding, accepted connections, upstream connection failures, per-direction byte totals, lifecycle recovery, and shutdown. Account passwords, bearer tokens, and request bodies are not logged.
