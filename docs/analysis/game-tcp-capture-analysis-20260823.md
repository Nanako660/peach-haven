# 原版游戏 TCP 启动帧分析（2026-08-23）

> **分类**：技术分析 / TCP 抓包协议  
> **状态**：已确认 (Confirmed by packet capture)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 证据来源

**Confirmed by packet capture or runtime observation**：本记录基于以下工作区文件：

- 原始抓包：`server/data/captures/tao-original-20260823-1605.pcap`
- TCP 重组结果：`server/data/captures/tao-original-20260823-1605-game-frames.json`
- TCP 摘要：`server/data/captures/tao-original-20260823-1605-game-tcp-summary.txt`
- 相关运行日志：`server/data/captures/tao-original-20260823-1605-logcat-filtered.txt`

抓包目标为运行时实际连接的 `3.0.140.171:21001`。该次 TCP 重组结果：

| 项目 | 结果 |
|---|---:|
| 客户端方向 TCP payload | 2045 bytes |
| 服务端方向 TCP payload | 6886 bytes |
| 客户端 TCP 分片序列缺口 | 0 |
| 服务端 TCP 分片序列缺口 | 0 |
| 重组帧数量 | 70 |

原始登录请求中的身份字段为 `OpenId=<TEST_OPENID>`、`UserId` 为空、`Account=<TEST_ACCOUNT>`、`SelectZone=0`。分析 JSON 对登录 body 做了脱敏，只保留 Token 长度和 SHA-256 指纹；原始 pcap 属于敏感输入，不应上传或提交到不受控位置。

## 登录和启动顺序

筛选服务端方向的关键帧后，实际序列为：

```text
CS_LOGIN_REQ(3)
  -> SC_HAND_SHAKE_NTF(7)
  -> SC_LOGIN_ACK(4)
  -> SC_STARTUP_INFO_NTF(25)  RoleBase
  -> SC_STARTUP_INFO_NTF(25)  RoleBag
  -> SC_STARTUP_INFO_NTF(25)  任务/图鉴等
  -> SC_STARTUP_INFO_NTF(25)  任务/签到等
  -> SC_STARTUP_INFO_EQUIP_NTF(26)
  -> SC_STARTUP_INFO_HERO_NTF(27)
  -> SC_STARTUP_INFO_END_NTF(28)
```

关键帧长度：

| 方向 | 消息号 | body 长度 | 说明 |
|---|---:|---:|---|
| C -> S | 3 | 899 | 登录请求 |
| S -> C | 7 | 18 | `CryptPass` 握手通知 |
| S -> C | 4 | 9 | `Error=0`、`ClientId` 非零 |
| S -> C | 25 | 152 | `RoleBase`、基础时间和区服 |
| S -> C | 25 | 38 | `RoleBag` |
| S -> C | 25 | 59 | 风险战斗、声望、图鉴、地址 |
| S -> C | 25 | 994 | 区域任务、通用任务、签到 |
| S -> C | 26 | 2 | 空的 `RoleEquipInfo` 消息 |
| S -> C | 27 | 114 | `RoleHeroInfo` 和空的 replay 信息 |
| S -> C | 28 | 0 | 启动结束 |

## 关键字段

### 登录响应

**Confirmed by packet capture or runtime observation**：`SCLoginAck(4)` 解码结果：

- `Error=0`
- `ClientId=29988810766942465`

这证明该原版运行已经通过真实游戏服登录校验，而不是收到兼容错误响应。

`SCHandShakeNtf(7)` 的 `CryptPass` 为 16 字符字符串。静态处理器只完成消息接收，不改变登录状态；因此它不是当前登录身份校验的来源，但为了保持真实服务端时序，fixture 会在存在该帧时重放它。

## 启动后的首批业务消息

启动结束后，原版客户端没有停在 28，而是立即发起一批初始化请求。抓包中确认的请求/响应对包括：

| 请求 | 响应 | 次数 | 请求 body | 响应 body |
|---:|---:|---:|---:|---:|
| `CS_PLAYER_INFO_REQ(23)` | `SC_PLAYER_INFO_ACK(24)` | 2 | 0 | 50 |
| `CS_GUIDE_SAVE_REQ(59)` | `SC_GUIDE_SAVE_ACK(60)` | 5 | 134-149 | 0 |
| `CS_GUIDE_GET_REQ(61)` | `SC_GUIDE_GET_ACK(62)` | 1 | 0 | 141 |
| `CS_PLAYER_RANK_REQ(166)` | `SC_PLAYER_RANK_ACK(167)` | 2 | 8/11 | 28/31 |
| `CS_MAIL_LIST_REQ(170)` | `SC_MAIL_LIST_ACK(171)` | 1 | 0 | 1043 |
| `CS_TRANSMIT_DATA_REQ(327)` | `SC_TRANSMIT_DATA_ACK(328)` | 4 | 21-28 | 19-26 |
| `CS_FRIEND_LIST_REQ(349)` | `SC_FRIEND_LIST_ACK(350)` | 1 | 0 | 0 |
| `CS_READ_DATA_LOAD_REQ(368)` | `SC_READ_DATA_LOAD_ACK(369)` | 1 | 0 | 0 |
| `CS_READ_DATA_SAVE_REQ(370)` | `SC_READ_DATA_SAVE_ACK(371)` | 1 | 7 | 0 |
| `CS_CONDITION_EVENT_REQ(374)` | `SC_CONDITION_EVENT_ACK(375)` | 1 | 5 | 0 |
| `CS_CHAT_STATE_QUERY_REQ(24146)` | `SC_CHAT_STATE_QUERY_ACK(24147)` | 1 | 0 | 2 |

同时还收到服务端主动通知 `376/55/184/189/204/226/393/24166/24176`，并持续进行 `CS_PING_REQ(1) -> SC_PING_ACK(2)` 心跳。

**Inferred and still requiring validation**：当前本地 `GameTcpServer` 只对登录、启动、377 订单和 76 钻石更新作出业务响应；`_handle_client` 对上述初始化请求保持连接但不返回对应 ACK。因此，即使 `4/7/25/26/27/28` 已经完整重放，APK 仍可能在主界面初始化阶段等待这些 ACK。下一阶段应优先恢复 23/24、59/60、61/62、170/171 和 376，再根据 logcat 的实际等待点扩展其他消息。

### 角色

第一个 `25` 中的 `RoleBase`：

| 字段 | 值 |
|---|---:|
| `RoleBase.Uid` | `7677134173358784641` |
| `RoleBase.Diamond` | `0` |
| `RoleBase.Coin` | `0` |
| `SelectZone` | `4` |
| `RoleBase` body 长度 | `59` |

logcat 同时记录了角色名“五龙神”和账号标识 `7677134173358784641`，与 `RoleBase.Uid` 一致。

第二个 `25` 中的 `RoleBag` body 长度为 `36`，包含两个 `Items` map 条目：

- map key `1`，`ItemData` body 长度 `16`
- map key `2`，`ItemData` body 长度 `16`

**Confirmed by packet capture or runtime observation**：原始数据中的角色和背包不是一个 25 包，而是多个 25 包的部分更新。客户端的 `ScStartupInfoNtf_SetUserInfo_MsgHandler` 会逐包合并，因此服务端必须保留这个顺序和分包边界。

## 对现有实现的影响

之前的实现假设同一个 `SCStartupInfoNtf(25)` 必须同时包含 `RoleBase` 和 `RoleBag`。这与真实抓包不一致，会导致：

1. fixture 校验在第一帧 25 因缺少 `RoleBag` 而拒绝；
2. 即使绕过校验，发送启动序列时对不含 `RoleBase` 的后续 25 继续执行钻石补丁也会失败；
3. 服务端无法准确保存完整启动数据。

本轮已修正：

- `extract_startup_parts()` 在整个 25 序列中分别寻找 `RoleBase` 和 `RoleBag`；
- fixture 校验允许多个连续 25，并要求组合后包含两部分；
- 重放时仅对含 field 4 `RoleBase` 的 25 做 field 8 钻石补丁；
- 不含 `RoleBase` 的 25、26、27、28 保持原始 body、序号和 flag；
- `server.fixture_tool from-capture` 可从分析 JSON 自动生成 fixture。
- `SC_HAND_SHAKE_NTF(7)` 若存在会在 `SC_LOGIN_ACK(4)` 前保留和重放。

## 已生成 fixture

已生成并通过校验：

`server/data/fixtures/captured-lily6985-local.json`

fixture 中的身份映射是本地测试映射，不是原始 Token 的复制：

```json
{
  "server_id": 4,
  "sdk_user_id": 1,
  "login_open_id": "1",
  "login_user_id": "",
  "game_uid": "7677134173358784641"
}
```

原始抓包身份 `OpenId=9227573` 与当前本地 SDK 用户 `OpenId=1` 不同，因此这里明确采用本地账号映射，避免把原始 SDK Token 或身份凭据带入本地服务。若要按原始账号身份测试，应先在本地 SDK 数据库建立明确的 `9227573 -> sdk_user_id` 映射，不应自动猜测。

## 结论等级

- **Confirmed by packet capture or runtime observation**：真实 TCP 头、无序列缺口、`3/4/25/26/27/28` 顺序、四个分段 25、角色 UID、区服和启动字段。
- **Confirmed by static analysis**：消息号含义、Protobuf 字段号和客户端逐条合并启动数据的处理器位置。
- **Inferred and still requiring validation**：除启动阶段外，后续业务消息的完整服务端状态管理仍需继续从实机操作抓包恢复；本次抓包虽然包含后续消息，但当前服务端只承诺登录、启动、订单和钻石状态更新。
