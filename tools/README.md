# Peach Haven - Toolchain & Upstream References

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

<p><b>Comprehensive catalog of third-party open-source tools, upstream repositories, and custom utilities used in the Peach Haven project.</b></p>

</div>

---

## Overview

The **Peach Haven** project combines third-party security, reverse-engineering, and Android SDK tools with custom Python utilities to analyze the target game (*Peach Utopia*, `com.IdolTime.Cards.game18`), reconstruct network protocols, and build the local compatibility server.

To maintain compliance and keep the Git repository clean, this project **does not bundle third-party binaries or proprietary packages**. Instead, this document provides upstream repository links, licenses, and environment setup instructions.

---

## Upstream Toolchain Matrix

| Tool / Framework | Upstream Repository / Official Site | License | Purpose in Peach Haven |
| :--- | :--- | :--- | :--- |
| **Apktool** | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) | Apache-2.0 | APK decoding, resource decompilation, Smali bytecode inspection, and package rebuilding |
| **Android Build-Tools** | [AOSP Build Tools](https://android.googlesource.com/platform/frameworks/base) | Apache-2.0 | Dalvik/ART bytecode compilation (`d8`), 4-byte ZIP alignment (`zipalign`), and APK signing (`apksigner`) |
| **Android Debug Bridge (ADB)** | [AOSP / adb](https://github.com/aosp-mirror/platform_system_core/tree/master/adb) | Apache-2.0 | Device/emulator communication, port forwarding (`adb forward`), and runtime logcat capture |
| **UnityPy** | [K0lb3/UnityPy](https://github.com/K0lb3/UnityPy) | MIT | Python extraction and parsing of Unity AssetBundles, serialized assets, and YooAsset package manifests |
| **Il2CppDumper** | [Perfare/Il2CppDumper](https://github.com/Perfare/Il2CppDumper) | MIT | Extracting C# method signatures, types, and string constants from `libil2cpp.so` + `global-metadata.dat` |
| **ILSpy** | [icsharpcode/ILSpy](https://github.com/icsharpcode/ILSpy) | MIT | Decompilation of managed assemblies (`Model.dll`, `View.dll`, `HotUpdate.dll`) |
| **dnSpy** | [dnSpyEx/dnSpy](https://github.com/dnSpyEx/dnSpy) | GPL-3.0 | Advanced .NET assembly analysis and C# protocol structure inspection |
| **tcpdump** | [the-tcpdump-group/tcpdump](https://github.com/the-tcpdump-group/tcpdump) | BSD-3-Clause | Low-level network packet capture on Android test devices / emulators |
| **Wireshark** | [wireshark/wireshark](https://github.com/wireshark/wireshark) | GPL-2.0 | Offline `.pcap` inspection, TCP stream reconstruction, and handshake sequence analysis |
| **7-Zip** | [ip7z/7zip](https://github.com/ip7z/7zip) | LGPL / BSD | Fast extraction, archive processing, and selective Dex injection in build scripts |
| **FastAPI** | [fastapi/fastapi](https://github.com/fastapi/fastapi) | MIT | Asynchronous HTTP framework powering the local SDK compatibility server (@ 8080) |
| **Uvicorn** | [encode/uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | High-performance ASGI web server for HTTP API endpoints |
| **PyCryptodome** | [Legrandin/pycryptodome](https://github.com/Legrandin/pycryptodome) | BSD-2-Clause | Cryptographic implementation for AES-128-ECB and PKCS7 padding |
| **Pydantic** | [pydantic/pydantic](https://github.com/pydantic/pydantic) | MIT | Data parsing, configuration management, and request schema validation |

---

## Project Custom Tooling

Located within the [`tools/`](./) directory and repository root:

```text
tools/
├── README.md                      # Toolchain catalog & upstream references (English)
├── README.zh-CN.md                # Toolchain catalog & upstream references (Chinese)
├── apk-relay/                     # Local dual-channel relay patch source & scripts
│   ├── README.md                  # Detailed relay architecture & patch pipeline doc
│   ├── src/                       # Java overlay & proxy source (RelayOverlay, RelayConfig)
│   ├── patch-sdk-domains.ps1      # Smali base-domain convergence patch
│   ├── patch-unity-player-activity.ps1 # Lifecycle hook injection
│   ├── patch-sdk-floating.ps1     # Floating window & overlay injection
│   └── build-local-relay.ps1      # Relay Dex compilation and APK rebuilder
├── analyze_game_tcp_pcap.py       # Offline Python PCAP parser & TCP stream reassembler
└── recover_game_tcp_protocol.py   # Protocol Message ID & structure recovery script
```

### 1. `tools/apk-relay/` (Client Patch Toolkit)
- Injects a lightweight loopback proxy (`classes3.dex`) into the client.
- Provides an in-game floating overlay to adjust target server endpoints at runtime.
- Converges hardcoded SDK endpoints to `http://127.0.0.1:8080`.
- See [`tools/apk-relay/README.md`](apk-relay/README.md) for architecture details.

### 2. `tools/analyze_game_tcp_pcap.py` (PCAP Analyzer)
- Pure Python script that reads raw `.pcap` files without external packet dissection dependencies.
- Reassembles fragmented TCP streams using sequence numbers and extracts 10-byte big-endian game protocol frames.
- Outputs structured frame timelines and Protobuf wire byte summaries to `server/data/captures/`.

### 3. `tools/recover_game_tcp_protocol.py` (Protocol Recovery Tool)
- Correlates decompiled C# message handlers with captured binary frames.
- Generates JSON mapping schemas for Message IDs, request-response pairs, and Protobuf field structures.

### 4. Root Entry Points
- [`patch.ps1`](../patch.ps1): Interactive one-click APK patch and re-signing pipeline.
- [`start.ps1`](../start.ps1) / [`stop.ps1`](../stop.ps1): Background lifecycle manager for HTTP SDK and Game TCP servers.
- [`manage.ps1`](../manage.ps1): Passthrough wrapper for `python -m server.cli`.

---

## Toolchain Environment Setup Guide

When building the client patch or analyzing raw assets, tools can be installed on system `PATH` or placed into the local `.tools/` workspace directory (which is automatically ignored by Git).

### Recommended Directory Layout for `.tools/`

```text
.tools/                            # Gitignored local workspace tool cache
├── adb/                           # Android platform-tools (adb.exe, etc.)
├── android-platform-35/           # android.jar (from Android SDK platforms/android-35)
├── android-build-tools/           # Android build-tools (d8.jar, zipalign.exe, apksigner.bat)
└── unitypy/                       # Standalone UnityPy extraction dependencies
```

### Automated Discovery
The [`patch.ps1`](../patch.ps1) script automatically checks for required build tools in the following priority:
1. Workspace `.tools/` directory (e.g. `.tools/android-build-tools/...`)
2. System environment variables and system `PATH` (`java`, `d8`, `zipalign`, `apksigner`, `7z`, `apktool`)

---

## Upstream Project Credits

We express our gratitude to the open-source authors and maintainers of the upstream tools listed above. Their foundational work makes mobile protocol analysis, reverse-engineering, and security research accessible to the community.
