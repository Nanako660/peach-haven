# 分析证据索引

> **分类**：实机与分析证据 (Evidence)  
> **状态**：已确认 (Confirmed artifacts index)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 原始与派生文件

| 文件/目录 | 类型 | 用途 |
| --- | --- | --- |
| `桃.apk` | 原始 APK | 静态分析输入 |
| `apktool.jar` | 工具 | APK 解包 |
| `decoded/` | 解包输出 | Manifest、assets、smali 相关输入 |
| `decoded_smali_20260822/` | smali 输出 | Java/Kotlin 网络和模型分析 |
| `files/` | 运行数据 | IL2CPP 元数据和 YooAsset 缓存 |
| `files.zip` | 归档 | `files/` 数据备份 |
| `.tools/unitypy/` | 工具 | Unity 资源解析 |

## 关键静态证据

| 结论 | 证据文件 |
| --- | --- |
| APK 包名和明文 HTTP | `decoded/AndroidManifest.xml` |
| 程序集清单 | `decoded/assets/bin/Data/ScriptingAssemblies.json` |
| AES 密钥和 transformation | `decoded_smali_20260822/smali/com/charles/weblib/network/interceptor/AESUtils.smali` |
| 请求封装、Token/deviceId/gameKey 注入和响应解密 | `decoded_smali_20260822/smali/com/charles/weblib/network/interceptor/AesInterceptor.smali` |
| SDK API 路径 | `decoded_smali_20260822/smali/com/charles/weblib/network/api/ApiService.smali` |
| ApiResult 字段 | `decoded_smali_20260822/smali/com/charles/weblib/network/result/ApiResult.smali` |
| 用户资料字段 | `decoded_smali_20260822/smali/com/charles/weblib/model/UserData.smali` |
| 系统信息字段 | `decoded_smali_20260822/smali/com/charles/weblib/model/GameSystemData.smali` |
| SDK 内置域名和缓存键 | `decoded_smali_20260822/smali/com/charles/weblib/network/SdkDomainManager.smali` |
| SDK 网络客户端回退调用 | `decoded_smali_20260822/smali/com/charles/weblib/network/NetworkClient.smali` |
| APK 直接修改、重签名与热更新影响 | `docs/analysis/apk-modification-feasibility.md` |
| YooAsset 静态 Manifest | `decoded/assets/yoo/DefaultPackage/PackageManifest_DefaultPackage_1.2.3.bytes` |
| YooAsset 设备缓存 | `files/yoo/DefaultPackage/` |
| IL2CPP 元数据 | `files/il2cpp/Metadata/global-metadata.dat` |

## 本地服务端证据

| 结论 | 证据文件 |
| --- | --- |
| FastAPI 路由和运行入口 | `server/main.py` |
| SQLite、PBKDF2 和 Token | `server/storage.py` |
| AES 协议实现 | `server/crypto.py` |
| 独立加密客户端 | `server/client.py` |
| 协议和接口测试 | `tests/test_server.py` |
| 数据库和日志 | `server/data/` |

## 动态/抓包证据

当前已记录：

- 热更新/CDN Host：`pxcdn.jhdwxp.com`
- 原版游戏 TCP 原始 pcap：`server/data/captures/tao-original-20260823-1605.pcap`
- 原版游戏 TCP 摘要：`server/data/captures/tao-original-20260823-1605-game-tcp-summary.txt`
- 原版游戏重组帧 JSON：`server/data/captures/tao-original-20260823-1605-game-frames.json`
- 原版游戏相关 logcat：`server/data/captures/tao-original-20260823-1605-logcat-filtered.txt`
- 原版游戏抓包报告：[`docs/analysis/original-game-tcp-capture-20260823.md`](../analysis/original-game-tcp-capture-20260823.md)
- 原版游戏启动帧分析：[`docs/analysis/game-tcp-capture-analysis-20260823.md`](../analysis/game-tcp-capture-analysis-20260823.md)
- 原版游戏玩法抓包分析：[`docs/analysis/gameplay-tcp-capture-20260823.md`](../analysis/gameplay-tcp-capture-20260823.md)
- 原版游戏玩法 pcap：`server/data/captures/tao-continuous-20260823-174438.pcap`
- 原版游戏玩法重组帧：`server/data/captures/tao-continuous-20260823-174438-game-frames.json`

本次动态证据确认：

- 原版包 `com.IdolTime.Cards.game18` 的 UID `<TEST_UID>` 连接 `3.0.140.171:21001`。
- 目标 TCP 流重组无 sequence gap，共重组 70 个游戏帧。
- 游戏登录和启动序列完整出现：`3 -> 4 -> 25 -> 26 -> 27 -> 28`。
- `1/2` 心跳请求/响应在进入游戏后按约 10 秒间隔出现。
- 玩法流中确认 6 次风险战斗、1 次单抽、1 次 `hplay_climax_data` 特殊剧情状态保存和 1 次英雄升级。

原始 pcap 包含真实认证 token 和角色数据；派生 JSON 对客户端登录 body 做了脱敏，原始证据只用于本地分析。

当前缺少：

- 完整热更新 URL 路径
- 请求方法和查询参数
- Manifest 响应内容
- Bundle 下载顺序
- 热更新版本和本地包版本对应关系

## 结论状态

### 已确认

- AES-128 ECB、PKCS5/PKCS7、密钥 `f237311e06398eac`。
- SDK 外层请求包含 `token`、`deviceId` 和 `data`。
- 服务器响应是同样的 AES 密文。
- SDK API 路径和关键模型字段已从 smali 恢复。
- 本地服务端测试和重启持久化已通过。

### 推断

- `pxcdn.jhdwxp.com` 是 YooAsset/HotUpdate 相关 CDN Host。
- 热更新后的代码可能调用尚未实现的 SDK 业务接口。
- SDK 备用域名回退可能导致单点域名替换不完整。

### 待验证

- 热更新完整根路径和 Manifest 规则。
- 当前线上热更新版本。
- HotUpdate 逻辑实际访问的全部服务端接口。
- APK 修改 SDK 域名后是否仍会被本地 `sdk_domains` 缓存覆盖。
