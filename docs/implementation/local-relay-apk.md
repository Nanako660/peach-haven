# 原始 APK 本地双通道中继包

> **分类**：系统实现 / 客户端补丁与 Relay  
> **状态**：已确认 (Confirmed by patch pipeline & device test)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 基线与边界

- 基线是工作区原始 `桃.apk`，只在 `build/original-relay-apk` 副本上修改。
- 原始 APK、`decoded`、`decoded_smali_20260822`、`files` 不作为输出目录修改。
- `pxcdn.jhdwxp.com`、YooAsset 和 HotUpdate 地址保持原值。
- 本地 HTTP 8080 仍是账号管理后台入口，负责注册、登录、Token 校验和 SDK API。
- 本地 TCP 21001 是游戏服务连接入口，不与 HTTP 8080 混用。

## APK 内部链路

```text
SDK /server API -> 127.0.0.1:8080 -> 配置的管理后台:8080
游戏 TCP        -> 127.0.0.1:21001 -> 配置的游戏服务端:21001
```

APK 中的 `SdkDomainManager` 候选基地址收敛到 `http://127.0.0.1:8080`。`ResAPIService.ServerListUrl` 对应的区服列表请求也使用本地 HTTP 入口；服务端 `/server/list` 返回区服 4 和 `127.0.0.1:21001`，因此游戏 TCP 连接会再次进入 APK 内置中继。

中继实现位于独立的 `classes3.dex`，不依赖外部 VPN 或 Android 全局代理。应用启动时先启动中继，再构造 `SdkManager`，避免 SDK 首个请求早于本地监听器。应用右上角的“转发”悬浮按钮可以修改管理后台和游戏服务端地址，配置保存在应用 SharedPreferences 中。

## 服务端配置

```powershell
python -m server.main
python -m server.game_tcp
```

服务端部署参数配置在 `server/config.toml`；可使用 `--config` 指定其他 TOML 文件。旧环境变量只对 TOML 未填写的字段生效。

APK 悬浮窗中的默认目标为开发机 `192.168.1.100`（或 `127.0.0.1`）。实际使用时将“账号管理后台”设置为运行 FastAPI 的主机，将“游戏服务端”设置为运行游戏 TCP 服务的主机；两个地址可以相同，也可以分开。

## 构建与签名

- 私钥：`build/local-sdk-test.keystore`（缺失时由一键脚本自动生成，已存在则复用）
- alias：`local-sdk-test`
- 当前产物：`dist/桃-local-relay-v3.apk`（一键导出，附 `*.sha256`）
- 中间产物：`build/local-relay-v3.apk`（ASCII 名）

一键构建（原包需手动提供，仓库不内置原包）：

```powershell
.\patch.ps1                       # 交互式输入原包路径
.\patch.ps1 -Apk <原始APK路径>
.\patch.ps1 -Clean -Apk <原始APK路径>
```

解码与 `SdkDomainManager` 域名收敛已纳入一键脚本，不再手工执行。产物已使用同一项目测试私钥完成 zipalign，以及 APK v1、v2、v3 签名验证。覆盖安装使用 `adb install -r`，未卸载应用，因此应用数据和首次安装时间保持不变。

## v3 日志

v3 增加了独立的 Android Logcat 标签：

```powershell
.tools/adb/adb.exe logcat -v threadtime -s LocalRelay:D LocalRelayOverlay:I LocalRelayConfig:I
```

日志覆盖以下节点：

- `LocalRelayConfig`：配置保存结果、后台和游戏上游地址、端口以及启用状态。
- `LocalRelayOverlay`：悬浮窗安装、点击、配置弹窗、校验失败、保存重启和手动停止。
- `LocalRelay`：启动/停止、监听绑定、生命周期恢复、客户端接入、上游连接、连接异常、每个方向的字节数和持续时间。

日志不会输出账号密码、Bearer Token 或 HTTP/TCP 请求正文。

## Git 版本管理

Git 记录的是可复现源码和构建入口，不提交 `build/` 下的解包目录、dex、APK、签名文件和临时日志：

- `tools/apk-relay/src/`：悬浮窗、中继控制器和配置源码。
- `tools/apk-relay/build-local-relay.ps1`：编译、D8、apktool、合并 `classes3.dex`、zipalign 和签名流程。
- `tools/apk-relay/patch-sdk-domains.ps1`：`SdkDomainManager` SDK 域名收敛补丁。
- `tools/apk-relay/patch-unity-player-activity.ps1`：应用生命周期恢复补丁。
- `tools/apk-relay/patch-sdk-floating.ps1`：SDK 浮窗与 Relay 菜单补丁。
- `tools/apk-relay/README.md`：构建与 Logcat 使用说明。
- `patch.ps1`：仓库根一键入口（解码 → 补丁 → 构建 → 导出）。
- 本文档：实现边界、产物和验证记录。

v3 SHA-256：`B1DBCA15F052F46DA37865FED343B41BCCBD8D26D06FA23C805836F7D1CA7543`。

## 当前验证状态

已验证：

- Python 服务测试与编译检查通过。
- `server.client` 登录、轨迹和 SDK 支付兼容冒烟通过。
- APK 覆盖安装成功。
- APK 日志显示本地 HTTP/TCP 中继先于 SDK 初始化启动。
- v3 在 `onStart/onResume` 调用 `ensureStarted`，用于应用回到前台后的中继自恢复。
- APK 的 `validateToken` 请求通过 `127.0.0.1:8080` 转发到管理后台。
- 原始 `/api/domain` 请求当前由兼容后台返回 404，未阻断 Token 校验，但仍属于待补齐的 SDK 兼容接口。

尚未确认：

- 设备当前在 Unity 资源初始化阶段报告 `[PATH] 所有 PATH 地址均不可用`，因此本轮没有进入 `/server/list` 和游戏 TCP 登录。
- 这不等同于 TCP 协议或账号注册链已失败；需要先在允许访问原始资源 CDN 或已有热更新缓存的环境重新验证。

## 主要验证命令

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server tests
python -m server.client
```
