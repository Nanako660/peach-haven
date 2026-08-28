# APK 游戏 TCP 逻辑恢复记录

> **分类**：技术分析 / TCP 协议恢复  
> **状态**：已确认 (Confirmed by static analysis & packet capture)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 结论

**Confirmed by static analysis**：APK 的托管程序集已经包含游戏 TCP 客户端的连接、分片收包、10 字节头编解码、Protobuf 动态解析、请求响应匹配、重连和心跳逻辑。主要来源是：

- `.tools/client_decompiled/Model.dll/IdolGame/SocketClient.cs`
- `.tools/client_decompiled/Model.dll/IdolGame/NetworkComponent.cs`
- `.tools/client_decompiled/Model.dll/IdolGame/NetworkComponentSystem.cs`
- `.tools/client_decompiled/View.dll/IdolGame/SDKLogin_LoginTask.cs`
- `.tools/client_decompiled/Model.dll/Serverproto/*.cs`

**Confirmed by packet capture/runtime observation**：2026-08-23 使用未修改的原版 `com.IdolTime.Cards.game18` 在模拟器上连接真实游戏服 `3.0.140.171:21001`，发送 `CSLoginReq(3)`，并收到 `SCLoginAck(4)`、四个 `SCStartupInfoNtf(25)`、`SCStartupInfoEquipNtf(26)`、`SCStartupInfoHeroNtf(27)` 和 `SCStartupInfoEndNtf(28)`。原始 pcap、帧重组结果和启动数据分析见 [`original-game-tcp-capture-20260823.md`](original-game-tcp-capture-20260823.md) 与 [`game-tcp-capture-analysis-20260823.md`](game-tcp-capture-analysis-20260823.md)。此前服务端返回 `SCLoginAck(error=1001)` 的直接原因是本地没有有效启动 fixture。

**Inferred and requiring validation**：仅凭 APK 静态文件无法恢复某个账号的真实 `RoleBase`、`RoleBag` 和其他启动状态；现在已有一份特定账号的真实启动帧，但不代表所有账号都可以共用这份存档。服务端不能用缺字段的伪造对象代替真实启动数据，否则客户端后续页面可能因缺少任务、商店、VIP、背包或配置状态而继续阻断。

## TCP 客户端

### 连接和地址

`NetworkComponent` 默认保存游戏 TCP 地址 `dev.g.idoltime.games` 和端口 `21001`。`NetworkComponentSystem.Awake` 会将 `AppConfig.runtimeAppServerUrl` 按 `host:port` 拆分，覆盖这两个值；`Init` 随后创建 `SocketClient` 并连接。

证据：

- `NetworkComponent.cs:46-48`
- `NetworkComponentSystem.cs:86-88`
- `NetworkComponentSystem.cs:867-873`

**Confirmed by static analysis**：因此，服务端返回的区服 `addr` 和 `port` 不是装饰字段，客户端会把它们转成运行时 TCP 目标。

### 连接行为

`SocketClient` 使用 `TcpClient.ConnectAsync`，连接超时为 5 秒；连接成功后保存 `NetworkStream`，触发 `OnConnectionStateChanged(true)`。断线会进入重连流程，自动重连上限为 5 次，手动重连上限为 3 次。

证据：`.tools/client_decompiled/Model.dll/IdolGame/SocketClient.cs:64-112,1023-1102,1379-1457`。

### 10 字节头

发送和接收均使用大端字节序：

| 偏移 | 长度 | 类型 | 含义 |
|---:|---:|---|---|
| 0 | 2 | `uint16` | Protobuf body 长度 |
| 2 | 2 | `uint16` | 消息号 |
| 4 | 4 | `int32` | 序号 `seq` |
| 8 | 2 | `uint16` | 标志 `flag` |

证据：`SocketClient.cs:1041-1055,1152-1244,1305-1324`。

客户端先累计完整 10 字节头，再按 `bodyLen` 累计完整消息体；TCP 分片不会被当作独立消息。消息体完成后，客户端根据消息号查找 Protobuf parser，再发布给 `NetworkComponent`。

### 动态 Protobuf 解析

构造函数调用 `_InitializeMessageTypeMap`。该方法扫描程序集中的 `IMessage` 类型，读取每个类型的 `Descriptor.Name`，将其解析为 `protoMsgId`，并缓存对应的 `MessageParser`。因此客户端不在 TCP 层硬编码每个消息的解析分支。

证据：`SocketClient.cs:1102-1118,1262-1303`。

### 心跳

客户端维护最后一次心跳时间；超出约 10 秒且没有暂停/重连时触发重连检查。2026-08-23 原版抓包实际观察到客户端消息 `1`（`CsPingReq`）和服务端消息 `2`（`ScPingAck`）各 5 次，客户端 body 长度为 9，服务端 body 长度为 7，时间间隔约 10 秒。

证据：`SocketClient.cs:1067-1085,1128-1147`。

## 已恢复消息号

以下消息号来自 `protoMsgId.cs`，字段来自对应生成的 Protobuf C# 文件。

| 方向 | 消息号 | 类型 | 状态 |
|---|---:|---|---|
| C -> S | 3 | `CSLoginReq` | **Confirmed by static analysis and packet capture** |
| S -> C | 4 | `SCLoginAck` | **Confirmed by static analysis and packet capture** |
| S -> C | 7 | `SCHandShakeNtf` | **Confirmed by static analysis and packet capture** |
| S -> C | 25 | `SCStartupInfoNtf` | **Confirmed by static analysis and packet capture** |
| S -> C | 26 | `SCStartupInfoEquipNtf` | **Confirmed by static analysis and packet capture** |
| S -> C | 27 | `SCStartupInfoHeroNtf` | **Confirmed by static analysis and packet capture** |
| S -> C | 28 | `SCStartupInfoEndNtf` | **Confirmed by static analysis and packet capture** |
| S -> C | 76 | `SCRoleBaseInfoNtf` | **Confirmed by static analysis** |
| C -> S | 377 | `CSOrderNoReq` | **Confirmed by static analysis** |
| S -> C | 378 | `SCOrderNoAck` | **Confirmed by static analysis** |

来源：`.tools/client_decompiled/Model.dll/Serverproto/protoMsgId.cs:14-16,50-56,136,622-624`。

本次原版抓包显示消息 7 位于消息 4 之前。`SCHandShakeNtf` 只有 field 1 `CryptPass`，客户端处理器为空操作；服务端仍应在存在该帧时保留并按原顺序重放。

## 登录协议

`CSLoginReq` 字段：

| 字段号 | 字段 | 类型 | 备注 |
|---:|---|---|---|
| 1 | `Platform` | `string` | 平台标识 |
| 2 | `SystemType` | `int32` | 当前登录代码设置为 `1` |
| 3 | `AuthToken` | `string` | SDK 登录 Token |
| 4 | `OpenId` | `string` | 当前 APK 登录代码明确设置 |
| 5 | `AuthType` | `string` | SDK 鉴权类型 |
| 7 | `GameVersion` | `int32` | 生成定义存在，当前构造代码未设置 |
| 8 | `Ip` | `string` | 生成定义存在 |
| 9 | `SelectZone` | `int32` | 选择区服 |
| 10 | `SubPlatform` | `string` | 子平台 |
| 11 | `UserId` | `string` | 当前登录构造代码未设置 |
| 12 | `DeviceCode` | `string` | 设备唯一标识 |
| 13 | `Account` | `string` | 仅 SDK 平台为 4 时设置 |
| 14 | `ClientTrackJson` | `string` | 客户端轨迹 JSON |

证据：

- 字段定义：`CSLoginReq.cs:16-166`
- 构造和发送：`SDKLogin_LoginTask.cs:296-350`

**Confirmed by static analysis**：当前 APK 的游戏登录身份主字段是 `OpenId`，不能把 `UserId` 当作必填主键。服务端现已按 `OpenId` 主匹配，只有旧请求没有 `OpenId` 时才兼容 `UserId`。

**Confirmed by packet capture/runtime observation**：本次原版登录请求 body 长度为 899 字节，字段值包括 `platform=18game`、`system_type=1`、`auth_type=18game`、`open_id=9227573`、`account=lily6985` 和存在的 `client_track_json`。`auth_token` 为 32 字符 opaque token，派生 JSON 只保留长度和指纹，不在文档中记录原值。

登录流程：

```text
SDK 登录取得 AccessToken/open_id
  -> AppConfig.runtimeAppServerUrl 解析 host:port
  -> NetworkComponent.Init 建立 TCP
  -> 注册消息 28 的完成回调
  -> SendStateChangeAsync<SCLoginAck>(3, CSLoginReq)
  -> 处理 SCLoginAck
  -> 等待 25/26/27/28 启动序列
```

证据：`SDKLogin_LoginTask.cs:319-366`。

## 启动数据

`SCStartupInfoNtf` 的已确认关键字段：

| 字段号 | 字段 | 类型 |
|---:|---|---|
| 1 | `ServerTime` | `uint64` |
| 2 | `CreateTime` | `uint64` |
| 3 | `SelectZone` | `int32` |
| 4 | `RoleBase` | `RoleBase` |
| 5 | `RoleBag` | `RoleBag` |
| 6 | `RoleRiskBattle` | `RoleRiskBattle` |
| 7 | `Profile` | `ProfileData` |
| 9 | `AreaTask` | `AreaTaskData` |
| 30 | `RoleRed` | `RoleRedData` |
| 32 | `GeneralTask` | `GeneralTaskData` |
| 115-127 | VIP、签到、订阅、设置、时区等 | 多种消息类型 |

证据：`SCStartupInfoNtf.cs:16-170`。

客户端收到 25 后会将其合并到 `UserDataKey.UserInfo`，更新区服、角色、背包、任务、VIP、地址等数据；收到 28 后结束登录等待流程。

证据：

- `ScStartupInfoNtf_SetUserInfo_MsgHandler.cs:42-134`
- `SDKLogin_LoginTask.cs:348-350`

**Confirmed by packet capture/runtime observation**：真实服务端连续发送多个部分更新的消息 25；本次四个 25 body 的帧长度为 `152`、`38`、`59`、`994` 字节，分别覆盖基础角色、背包、风险战斗/图鉴/地址以及任务/签到等数据。26 为 `2` 字节，27 为 `114` 字节，28 为 `0` 字节。`RoleBase` 和 `RoleBag` 位于不同的 25 帧，fixture 必须完整保留整个 25 序列以及消息 26/27/28 的原始帧。当前服务端只对含 field 4 `RoleBase` 的 25 做 wire-level 钻石替换，未知字段和其他启动数据保持原样。

## 角色和背包

### `RoleBase`

| 字段号 | 字段 | 类型 |
|---:|---|---|
| 1 | `Uid` | `uint64` |
| 2 | `NickName` | `string` |
| 3 | `Signature` | `string` |
| 4 | `Gender` | `int32` |
| 7 | `Coin` | `uint64` |
| 8 | `Diamond` | `uint32` |
| 9 | `Exp` | `AccumLevel` |
| 16 | `HeadId` | `int32` |
| 26 | `HeroExp` | `uint64` |
| 29 | `AreaId` | `int32` |
| 33 | `IsSendDefaultItem` | `bool` |
| 34 | `EquipExp` | `uint64` |
| 130 | `DailyResetTimeStamp` | `uint64` |
| 149 | `OnlineStamp` | `uint64` |
| 150 | `OfflineStamp` | `uint64` |
| 153 | `WeekResetTimeStamp` | `uint64` |

证据：`RoleBase.cs:16-160`。

### `RoleBag`

| 字段号 | 字段 | 类型 |
|---:|---|---|
| 1 | `Items` | `map<uint64, ItemData>` |
| 2 | `NextItemId` | `uint64` |

证据：`RoleBag.cs:16-80`。

**Inferred and requiring validation**：静态定义能够确认 `RoleBase.Diamond` 的字段号和类型，但不能证明所有商品都只通过这个字段结算。当前实现边界仍限定为六档钻石商品，不处理普通背包物品、礼包补偿或未确认协议。

## 订单协议

`CSOrderNoReq`：

| 字段号 | 字段 | 类型 |
|---:|---|---|
| 1 | `Platform` | `string` |
| 2 | `ServerId` | `int32` |
| 3 | `ShopId` | `int32` |
| 4 | `GoodsId` | `int32` |
| 5 | `Quantity` | `int32` |
| 6 | `OwnerKey` | `string` |

`SCOrderNoAck`：

| 字段号 | 字段 | 类型 |
|---:|---|---|
| 1 | `Error` | `int32` |
| 2 | `OrderNo` | `uint64` |
| 3 | `NotifyUrl` | `string` |
| 4 | `ShopId` | `int32` |
| 5 | `GoodsId` | `int32` |
| 6 | `Quantity` | `int32` |
| 7 | `OrderPrice` | `int32` |

证据：`CSOrderNoReq.cs:16-100`、`SCOrderNoAck.cs:16-120`、游戏内支付调用点 `SDKComponentSystem.cs:316-...`。

**Confirmed by static analysis**：`OrderNo` 是 `uint64`，不能按字符串或 `int32` 编码；`OrderPrice` 是 `int32`。服务端当前 wire codec 已按这两个类型编码。

## 在线角色更新

`SCRoleBaseInfoNtf`：

| 字段号 | 字段 | 类型 |
|---:|---|---|
| 1 | `Coin` | `uint64` |
| 2 | `Diamond` | `uint32` |
| 3 | `RoleBase` | `RoleBase` |
| 4 | `ResList` | repeated `KeyValueType` |
| 5 | `RepressSkillPvpVal` | `int32` |

证据：`SCRoleBaseInfoNtf.cs:16-120`。

**Confirmed by static analysis**：在线到账至少要同时更新外层字段 2 和嵌套 `RoleBase` 字段 8；服务端已按此策略发送 76。是否还需要同步其他资源字段，要通过实际游戏操作或抓包继续验证。

## 当前服务端与恢复结果的对应关系

| 项目 | 当前状态 |
|---|---|
| TCP 头读写 | 已实现，10 字节大端，保留 `seq/flag` |
| 登录字段 | 已按 `OpenId` 主匹配，`UserId` 兼容旧 fixture |
| Token 校验 | 已校验本地 SDK session 与 fixture `sdk_user_id` |
| 启动帧 | 依赖本地 fixture，严格要求 `4/25/26/27/28`，允许多个 25 分片 |
| 启动顺序 | 按 fixture 原始顺序重放 |
| 未知字段 | 通过原始 wire body 保留 |
| 钻石补丁 | 只改 `RoleBase` field 8；76 同步外层 field 2 和内层 field 8 |
| 真实角色数据 | 已从原版 TCP 抓包恢复一份角色启动模板；其他账号仍需独立映射或抓包 |

## 恢复边界和下一步

1. 保留现有服务端实现和测试，不构造缺字段的伪造启动对象。
2. 使用 `tools/recover_game_tcp_protocol.py` 扫描反编译程序集，检查协议定义是否与本文一致。
3. 使用 `python -m server.fixture_tool from-capture ...` 从允许的本地游戏 TCP 被动捕获生成 fixture。
4. 重新实机验证：`/server/list -> TCP connect -> 3/4 -> 25/25/.../26/27/28 -> 主界面`。
5. 如果收到完整启动序列后仍卡住，再根据缺失的后续消息继续恢复；不要把 SDK HTTP、YooAsset/HotUpdate 或 CDN 流量混入游戏 TCP fixture。
