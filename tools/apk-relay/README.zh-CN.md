# 本地中继 APK 补丁方案 (Local Relay APK)

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

</div>

> **分类**：系统实现 / 客户端中继补丁工具  
> **状态**：已确认 (Confirmed)  
> **免责声明**：本工具与文档仅用于逆向工程、安全研究与技术学习。

本目录包含带悬浮调试窗的中继 APK 变体的源码与构建脚本。

中继在应用内部暴露了两个本地回环监听器：

- `127.0.0.1:8080`：转发至账号管理 HTTP SDK 服务端。
- `127.0.0.1:21001`：转发至游戏 TCP 服务端。

右上角悬浮按钮允许在运行时动态编辑这两个上游地址。配置保存在应用的私有 `SharedPreferences` 中，且绝不在日志中输出用户凭证。

## 一键补丁 (One-Click Patch)

根目录下的 [`patch.ps1`](../../patch.ps1) 能够从用户提供的原版 APK 执行完整补丁流水线。由于本仓库不包含原版 APK，必须手动指定输入路径：

```powershell
.\patch.ps1                       # 交互式提示输入原版 APK 路径
.\patch.ps1 -Apk ./original.apk
.\patch.ps1 -Clean -Apk ./original.apk   # 强制清理缓存并重新解码
```

流水线执行步骤：

1. 使用 apktool 将原版 APK 解码至 `build/original-relay-apk`。
2. `patch-sdk-domains.ps1` — 将 `SdkDomainManager.smali` 中的 5 个基础域名重写为 `http://127.0.0.1:8080`。
3. `patch-unity-player-activity.ps1` — 将生命周期恢复代码注入到 `UnityPlayerActivity`。
4. `patch-sdk-floating.ps1` — 请求 SDK 悬浮窗并添加 Relay 菜单操作项。
5. 将 `src/` 编译为 `classes3.dex`，使用 apktool 重新打包，注入 Dex，执行 zipalign 对齐并签名。
6. 将已签名的 APK 及其 SHA-256 哈希值导出至 `dist/`。

签名密钥库 `build/local-sdk-test.keystore` 在首次使用时自动生成并长期复用，确保后续覆盖安装时签名一致。

## 构建脚本一览

- `build-local-relay.ps1` — 构建阶段核心脚本（打补丁、编译 Dex、打包、对齐、签名）。由 `patch.ps1` 解码后调用。
- `patch-sdk-domains.ps1` — SDK 基础域名收敛补丁。
- `patch-unity-player-activity.ps1` — 生命周期恢复注入补丁。
- `patch-sdk-floating.ps1` — SDK 悬浮窗与 Relay 菜单补丁。
- `patch-appconfig-urls.ps1` — **旧版** 字节级 URL 重写脚本（已由 smali 域名重写方案替代，v3 流水线不再使用）。

## Logcat 日志捕获

使用以下日志标签跟踪中继运行状态：

```powershell
.tools/adb/adb.exe logcat -v threadtime -s LocalRelay:D LocalRelayOverlay:I LocalRelayConfig:I
```

日志会输出配置加载、监听器绑定、连接接受、上游连接失败、双向传输字节统计与生命周期恢复事件，绝不输出用户密码、Token 或原始请求体。
