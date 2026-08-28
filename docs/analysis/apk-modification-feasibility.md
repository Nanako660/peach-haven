# APK 直接修改可行性分析

> **分类**：技术分析 / 客户端架构  
> **状态**：已确认 (Confirmed by static analysis & runtime capture)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 分析状态

- 分析日期：2026-08-22
- 原始 APK：`桃.apk`
- 包名：`com.IdolTime.Cards.game18`
- 当前结论：技术上可直接修改并重签 APK，但完整本地支付闭环不能只修改一个 URL。
- 本次分析未修改 `桃.apk`，也未修改 `decoded`、`decoded_smali_20260822`、`files` 或 YooAsset/HotUpdate 资源。

## 一、结论摘要

直接修改 APK 分为三个不同层次：

1. Android Java/Kotlin SDK 层：可行性高。SDK 域名、缓存键和故障转移逻辑已经在 smali 中定位。
2. Unity 托管代码层：可行性中等。游戏区服发现和登录流程位于 Unity 程序集/热更新代码中，`ResAPIService.ServerListUrl` 的定义尚未在现有 C# 反编译输出中定位。
3. IL2CPP/native 层：可行性低，不建议作为第一方案。没有必要为了替换服务器地址直接修改 `libil2cpp.so`。

因此，稳定测试包的推荐方向是：

- 先修改 SDK 域名层，使登录、账户和 `spend/create2` 指向本地 FastAPI；
- 再定位并修改游戏侧 `ServerListUrl`，使 `/server/list` 返回本地 TCP 地址；
- 保留 `pxcdn.jhdwxp.com`、YooAsset 和 HotUpdate 地址不变；
- 不修改 `libil2cpp.so`，除非后续证据证明目标地址只存在于 native 层。

## 二、调用链与修改边界

### 2.1 区服发现链

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**

客户端实际发送：

```text
POST https://px-api.zkifae.cn/server/list
Content-Type: application/json
Authorization: Bearer <token>
```

请求体包含：

```json
{
  "platform": "18game",
  "open_id": "1",
  "version": "0.11",
  "device_id": "<TEST_DEVICE_ID>"
}
```

响应中的 `server_id`、`addr` 和 `port` 决定后续游戏 TCP 连接。真实响应中区服 4 位于 `my_servers`，TCP 端口为 `21001`。

**Confirmed by static analysis（静态分析确认）**

`View.dll` 中的 `ApiService` 使用：

```csharp
(useServerListUrl ? ResAPIService.ServerListUrl : AppConfig.loginhttpServerUrl) + path
```

发送区服列表时调用：

```csharp
PostAsync("/server/list", jsonBody, useServerListUrl: true)
```

收到区服后，客户端会将选中的地址写入 `AppConfig.runtimeAppServerUrl`，再用于游戏 TCP 登录。

证据：

- `.tools/client_decompiled/View.dll/IdolGame/ApiService.cs`
- `.tools/client_decompiled/View.dll/IdolGame/UIHasAccountTplSystem.cs`

### 2.2 SDK API 链

**Confirmed by static analysis（静态分析确认）**

SDK 的通用网络层不是 `ResAPIService.ServerListUrl`。`SdkDomainManager` 维护独立的候选基地址：

```text
https://bjyinhegame.com
https://wangcaitt.com
https://shouyek.com
https://huochechushou.com
https://tywhtg.com
```

`NetworkClient` 会根据当前基地址、候选列表和失败状态进行轮换。SDK 还使用本地缓存键：

```text
sdk_domains
```

因此，只替换一个 SDK URL 或只修改 `/server/list`，都不能保证所有 SDK 请求都进入本地服务。

证据：

- `decoded_smali_20260822/smali/com/charles/weblib/network/SdkDomainManager.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/network/NetworkClient.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/storage/KVStore.smali`

### 2.3 游戏 TCP 链

**Confirmed by static analysis（静态分析确认）**

区服列表返回的 `addr:port` 会被用于游戏长连接。当前本地服务端已实现：

```text
CS_LOGIN_REQ(3)
SC_STARTUP_INFO_NTF(25/26/27/28)
CS_ORDER_NO_REQ(377)
SC_ORDER_NO_ACK(378)
SCRoleBaseInfoNtf(76)
```

APK 侧地址切换成功后，仍需要本地 TCP 服务端、fixture 和 SQLite 结算逻辑同时可用。只修改 APK 地址不会自动解决 Protobuf 字段、角色映射或钻石持久化问题。

## 三、APK 内部结构对可修改性的影响

### 3.1 Android Manifest 与明文 HTTP

**Confirmed by static analysis（静态分析确认）**

`AndroidManifest.xml` 包含：

```xml
android:usesCleartextTraffic="true"
android:networkSecurityConfig="@xml/network_security_config"
```

`network_security_config.xml` 的基础配置为：

```xml
<base-config cleartextTrafficPermitted="true" />
```

因此，测试包可以使用类似下面的本地地址：

```text
http://192.168.1.100:8080/
```

当前没有证据表明必须通过 native TLS 层才能访问本地 HTTP。应用网络层搜索也未发现针对这些 SDK 域名的自定义证书 pinning；重签后的实机仍需验证这一点。

证据：

- `decoded/AndroidManifest.xml`
- `decoded/res/xml/network_security_config.xml`
- `decoded_smali_20260822/smali/com/charles/weblib/network/NetworkClient.smali`

### 3.2 Unity IL2CPP、HybridCLR 与 YooAsset

**Confirmed by static analysis（静态分析确认）**

APK 的运行时包含：

- `libil2cpp.so`
- `global-metadata.dat`
- `HotUpdate.dll`
- `YooAsset.dll`
- `HybridCLR.Runtime.dll`

`HybridDllManager` 会加载 `Hot.Entrance`，说明部分游戏逻辑不是单纯固定在 Android smali 中。项目中还存在提取出的托管 DLL 资源，例如：

```text
.tools/files_extracted/Assets/Res/DLL/View.dll.bytes
```

其中可以检索到 `ResAPIService` 和 `ServerListUrl` 符号，但当前 C# 反编译结果只显示使用位置，尚未显示其定义。

**Inferred and still requiring validation（推断，仍需验证）**

- `ResAPIService.ServerListUrl` 可能位于未导出的程序集、热更新 DLL 或由运行时配置注入。
- 修改 APK 内的静态 DLL 资源可能被 YooAsset 下载的新版资源覆盖。
- 如果当前设备已经缓存了较新的热更新包，修改 APK 内置资源不一定影响最终执行代码。

证据：

- `.tools/client_decompiled/Base.dll/Base/GameUpdate/HybridDllManager.cs`
- `decoded/assets/bin/Data/ScriptingAssemblies.json`
- `.tools/files_extracted/Assets/Res/DLL/View.dll.bytes`
- `docs/analysis/hot-update-yooasset.md`

## 四、直接修改的候选位置

| 层次 | 候选文件/位置 | 可行性 | 主要风险 |
| --- | --- | --- | --- |
| SDK 硬编码域名 | `SdkDomainManager.smali` | 高 | 域名缓存和故障转移仍可能覆盖修改 |
| SDK 故障转移 | `NetworkClient.smali` | 高 | 需要保持 Retrofit/OkHttp 初始化合法 |
| SDK 域名缓存 | `sdk_domains` 对应 KVStore 逻辑 | 中 | 旧缓存可能在启动时重新加入候选列表 |
| 游戏区服地址 | `ResAPIService.ServerListUrl` 所在托管程序集 | 中 | 定义位置尚未定位，可能属于热更新资源 |
| 游戏登录地址 | `AppConfig.appServerUrl`/`runtimeAppServerUrl` 相关逻辑 | 中 | 运行时会被 `/server/list` 响应覆盖 |
| Android Manifest | `AndroidManifest.xml`、网络安全配置 | 高 | 当前配置已允许明文，通常不需改 |
| IL2CPP native | `libil2cpp.so`、metadata | 低 | 逆向、重定位和 ABI 风险高，修改面大 |
| YooAsset/HotUpdate | CDN、Manifest、Bundle、DLL | 暂不建议 | 会扩大范围，并违反当前验证阶段边界 |

## 五、重打包与签名约束

**Confirmed by read-only APK tooling validation（只读工具验证确认）**

原始 APK 当前通过：

- APK Signature Scheme v1
- APK Signature Scheme v2
- zip alignment 检查

工程内已有：

- `apktool.jar`
- `.tools/android-build-tools/extracted/android-15/apksigner.bat`
- `.tools/android-build-tools/extracted/android-15/zipalign.exe`

修改后必须重新执行：

1. APK 解包或替换目标文件；
2. 重新构建 APK；
3. `zipalign`；
4. 使用新的测试密钥签名；
5. `apksigner verify --verbose`；
6. 在测试设备安装验证。

由于原始签名私钥不可用，重签包通常不能覆盖已经安装的原包。常见结果是：

- 使用相同包名：需要先卸载原包，可能丢失应用数据；
- 使用不同包名：可并行安装，但 Android 数据目录、缓存和部分 SDK 绑定状态不再复用。

当前未发现明确的应用内签名校验，但这只能说明静态搜索没有找到相关调用，不能替代实机验证。

## 六、为什么不能只改一个 URL

要让 APK 稳定进入本地支付闭环，至少需要同时满足：

```text
SDK 登录基址 -> 本地 FastAPI:8080
/server/list -> 返回本机 TCP 地址
游戏 TCP -> 本地 21001
启动 fixture -> 与客户端实际消息顺序一致
spend/create2 -> 能识别游戏订单
SQLite -> 原子结算角色钻石
在线连接 -> 收到 76 更新
```

只修改 `ServerListUrl` 的结果可能是：

- APK 能看到本地区服，但 SDK 登录仍访问原域名；
- SDK 登录成功，但域名失败转移又回到原始候选域名；
- TCP 已连接，但启动数据缺失导致客户端断开；
- 支付接口返回成功，但角色没有收到可识别的钻石更新；
- 重启或热更新后又恢复原地址。

## 七、推荐实施顺序

### 阶段 0：保留原始输入

- 复制 `桃.apk` 为测试副本；
- 对原始 APK 记录 SHA-256；
- 所有修改只在新目录进行；
- 不覆盖现有 `decoded`、`files`、缓存和抓包结果。

### 阶段 1：定位托管代码地址定义

- 从 `.tools/files_extracted/Assets/Res/DLL/View.dll.bytes` 解析类型和字段；
- 定位 `ResAPIService.ServerListUrl` 的声明、静态初始化和赋值来源；
- 确认该 DLL 是 APK 内置版本还是设备热更新版本；
- 确认 `AppConfig.loginhttpServerUrl` 的实际来源。

### 阶段 2：先做最小 SDK 路由修改

- 仅在测试副本中修改 `SdkDomainManager`/`NetworkClient`；
- 将所有候选基地址收敛到本地 SDK 地址；
- 保持 API 路径、AES 协议和响应结构不变；
- 不修改 `pxcdn.jhdwxp.com`。

### 阶段 3：修改游戏区服发现

- 将 `ResAPIService.ServerListUrl` 指向本地测试地址，或在测试环境中使用等价的路径转发；
- 本地 `/server/list` 返回 `server_id=4`、本机局域网 IP 和 `21001`；
- 区服放入 `my_servers`，保持客户端自动选择行为。

### 阶段 4：重打包安装验证

按以下顺序观察日志：

```text
/server/list
SDK Login
TCP connect 21001
CS_LOGIN_REQ(3)
SC_STARTUP_INFO_NTF(25/26/27/28)
CS_ORDER_NO_REQ(377)
spend/create2
SCRoleBaseInfoNtf(76)
```

### 阶段 5：确认热更新影响

- 对比首次启动和已有缓存启动的行为；
- 确认 `View.dll`/`HotUpdate.dll` 是否被重新下载；
- 如果热更新覆盖地址修改，再单独制定热更新测试方案；
- 在没有证据前不修改 CDN 或线上资源。

## 八、验收标准

直接修改 APK 的第一阶段只应判定以下结果：

- APK 能安装并启动；
- SDK 请求进入本地 FastAPI；
- `/server/list` 被调用并返回本地 TCP 地址；
- APK 连接本地 `21001`；
- `CS_LOGIN_REQ(3)` 被本地 TCP 服务收到；
- 启动数据按照 fixture 顺序发送；
- 不访问原始支付回调地址；
- 不改变 YooAsset/HotUpdate/CDN 地址。

只有以上条件全部满足后，才继续验证订单 377、支付结算和钻石消息 76。

## 九、当前未解决问题

1. `ResAPIService.ServerListUrl` 的声明和最终赋值位置尚未定位。
2. `AppConfig.loginhttpServerUrl` 的最终来源尚未完全确认。
3. 当前设备实际加载的是 APK 内置 DLL 还是热更新 DLL，尚未通过新一轮运行日志确认。
4. 重签测试包是否触发 SDK、渠道或服务端的签名/包名校验，尚未实机验证。
5. APK 修改后是否会因 `sdk_domains` 缓存或网络失败转移重新访问原始域名，尚未实机验证。

## 相关文档

- [`apk-overview.md`](apk-overview.md)
- [`sdk-domain-manager.md`](sdk-domain-manager.md)
- [`hot-update-yooasset.md`](hot-update-yooasset.md)
- [`client-payment-chain-analysis.md`](client-payment-chain-analysis.md)
- [`../implementation/local-server.md`](../implementation/local-server.md)
