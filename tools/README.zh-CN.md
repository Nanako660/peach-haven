# Peach Haven - 工具链与原始仓库引用

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

<p><b>Peach Haven 项目中涉及的所有第三方开源工具、上游原始仓库与自研实用工具全景索引。</b></p>

</div>

---

## 概述

**Peach Haven** 项目结合了第三方安全逆向、网络分析与 Android SDK 工具链，配合自研的 Python 脚本，用于对目标游戏（《蜜桃乌托邦 / *Peach Utopia*》，`com.IdolTime.Cards.game18`）进行逆向工程分析、协议恢复并构建本地兼容服务端。

为保持 Git 仓库轻量及严格遵守开源合规，本仓库**不内置或分发任何第三方大型二进制工具包或专有资产**。本文档详细列出了各工具的官方原始仓库、开源许可证以及本地环境配置指南。

---

## 第三方上游工具链矩阵

| 工具 / 框架名称 | 官方原始仓库 / 主页 | 开源许可证 | 在 Peach Haven 中的用途 |
| :--- | :--- | :--- | :--- |
| **Apktool** | [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) | Apache-2.0 | 客户端 APK 解包、资源解码、Smali 字节码反编译与重打包 |
| **Android Build-Tools** | [AOSP Build Tools](https://android.googlesource.com/platform/frameworks/base) | Apache-2.0 | Dalvik/ART 字节码编译 (`d8`)、4 字节 ZIP 对齐 (`zipalign`) 与签名 (`apksigner`) |
| **Android Debug Bridge (ADB)** | [AOSP / adb](https://github.com/aosp-mirror/platform_system_core/tree/master/adb) | Apache-2.0 | 设备/模拟器通信、端口转发 (`adb forward`) 与运行时 Logcat 捕获 |
| **UnityPy** | [K0lb3/UnityPy](https://github.com/K0lb3/UnityPy) | MIT | Python 下提取与解析 Unity AssetBundle 资源包、SerializedFile 与 YooAsset 资产清单 |
| **Il2CppDumper** | [Perfare/Il2CppDumper](https://github.com/Perfare/Il2CppDumper) | MIT | 从 `libil2cpp.so` 与 `global-metadata.dat` 提取 C# 方法签名、类型与字符串符号表 |
| **ILSpy** | [icsharpcode/ILSpy](https://github.com/icsharpcode/ILSpy) | MIT | 反编译热更托管程序集（`Model.dll`、`View.dll`、`HotUpdate.dll`）中的 C# 代码 |
| **dnSpy** | [dnSpyEx/dnSpy](https://github.com/dnSpyEx/dnSpy) | GPL-3.0 | 深度 .NET 程序集分析与 C# 网络协议数据结构还原 |
| **tcpdump** | [the-tcpdump-group/tcpdump](https://github.com/the-tcpdump-group/tcpdump) | BSD-3-Clause | Android 测试设备/模拟器底层的原始网络数据包抓取 |
| **Wireshark** | [wireshark/wireshark](https://github.com/wireshark/wireshark) | GPL-2.0 | 离线 `.pcap` 抓包分析、TCP 流重组与时序交互分析 |
| **7-Zip** | [ip7z/7zip](https://github.com/ip7z/7zip) | LGPL / BSD | 构建流水线中对 APK 内部特定文件与归档的高效解压与替换 |
| **FastAPI** | [fastapi/fastapi](https://github.com/fastapi/fastapi) | MIT | 本地 HTTP SDK 兼容服务端核心框架（端口 8080） |
| **Uvicorn** | [encode/uvicorn](https://github.com/encode/uvicorn) | BSD-3-Clause | 高性能 ASGI 异步 HTTP 服务器实现 |
| **PyCryptodome** | [Legrandin/pycryptodome](https://github.com/Legrandin/pycryptodome) | BSD-2-Clause | 实现 SDK 通信中 AES-128-ECB 与 PKCS7 填充加解密算法 |
| **Pydantic** | [pydantic/pydantic](https://github.com/pydantic/pydantic) | MIT | 数据结构与请求体验证、服务配置解析与类型约束 |

---

## 本项目内置自研工具集

位于 [`tools/`](./) 目录与仓库根目录：

```text
tools/
├── README.md                      # 工具链全景文档与上游索引 (英文版)
├── README.zh-CN.md                # 工具链全景文档与上游索引 (中文版)
├── apk-relay/                     # 本地双通道中继注入源码与补丁脚本
│   ├── README.md                  # 详细的中继架构与补丁流水线说明
│   ├── src/                       # Java 悬浮调试窗与代理源码 (RelayOverlay, RelayConfig)
│   ├── patch-sdk-domains.ps1      # Smali SDK 域名收敛补丁
│   ├── patch-unity-player-activity.ps1 # 生命周期恢复注入
│   ├── patch-sdk-floating.ps1     # 悬浮窗请求与菜单注入
│   └── build-local-relay.ps1      # 中继 Dex 编译与 APK 重打包签名
├── analyze_game_tcp_pcap.py       # 离线 PCAP 解析与 TCP 流重组分析工具
└── recover_game_tcp_protocol.py   # 游戏 TCP 协议消息映射自动恢复工具
```

### 1. `tools/apk-relay/` (客户端补丁工具集)
- 将轻量级本地回环代理（`classes3.dex`）注入到客户端 APK 中。
- 提供游戏内右上角悬浮调试窗，允许在运行时动态调整服务端目标地址。
- 将硬编码的 SDK 域名收敛至 `http://127.0.0.1:8080`。
- 架构细节参见 [`tools/apk-relay/README.md`](apk-relay/README.md)。

### 2. `tools/analyze_game_tcp_pcap.py` (PCAP 抓包分析器)
- 纯 Python 脚本，无需复杂的抓包依赖即可直接解析原生 `.pcap` 文件。
- 按 TCP 序列号（Sequence Number）精确重组分片，提取 10 字节大端协议帧。
- 将结构化的帧交互时序与 Protobuf 原始字节摘要输出至 `server/data/captures/`。

### 3. `tools/recover_game_tcp_protocol.py` (协议恢复工具)
- 将反编译得到的 C# 消息处理类与捕获的二进制帧进行关联匹配。
- 自动生成 Message ID 映射表、请求-响应对关系及 Protobuf 字段结构定义。

### 4. 根目录一键入口
- [`patch.ps1`](../patch.ps1)：交互式或参数化的一键 APK 补丁与重签名流水线。
- [`start.ps1`](../start.ps1) / [`stop.ps1`](../stop.ps1)：HTTP SDK 与游戏 TCP 双服务后台生命周期管理脚本。
- [`manage.ps1`](../manage.ps1)：`python -m server.cli` 通用管理透传脚本。

---

## 本地工具链环境配置指南

当需要制作客户端补丁或深入分析资源时，相关工具可直接安装至系统 `PATH` 环境变量，或放置在工作区根目录下的 `.tools/` 文件夹中（已在 `.gitignore` 中配置忽略）。

### 推荐的 `.tools/` 目录结构

```text
.tools/                            # 本地工作区工具缓存 (已 gitignore)
├── adb/                           # Android platform-tools (adb.exe 等)
├── android-platform-35/           # android.jar (来自 Android SDK platforms/android-35)
├── android-build-tools/           # Android build-tools (d8.jar, zipalign.exe, apksigner.bat)
└── unitypy/                       # 独立 UnityPy 资产提取环境
```

### 自动探测机制
[`patch.ps1`](../patch.ps1) 脚本会自动按以下优先级寻找构建工具链：
1. 本地 `.tools/` 目录（如 `.tools/android-build-tools/...`）；
2. 系统环境变量与系统 `PATH`（`java`、`d8`、`zipalign`、`apksigner`、`7z`、`apktool`）。

---

## 致谢与上游开源项目

向以上所有第三方开源工具与库的作者及维护者致以诚挚的谢意。开源社区卓越的底层基础设施让移动端逆向工程、协议分析与安全研究变得更加规范和高效。
