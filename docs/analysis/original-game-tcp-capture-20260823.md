# 原版游戏真实 TCP 抓包报告（2026-08-23）

> **分类**：技术分析 / TCP 抓包协议  
> **状态**：已确认 (Confirmed by packet capture)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 结论摘要

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：在未修改原版 APK 的情况下，模拟器成功连接真实游戏 TCP 服务，并完成了游戏登录和启动数据交换。

- 包名：`com.IdolTime.Cards.game18`
- 原版版本：`1.2.3`
- 设备：`emulator-5556`，Android 15，x86_64
- 模拟器地址：`10.0.2.15`
- 真实 TCP 目标：`3.0.140.171:21001`
- 应用进程：PID `31954`，UID `<TEST_UID>`
- 观察到账户：`<TEST_ACCOUNT>`，`open_id=<TEST_OPENID>`
- 完整启动序列：`CSLoginReq(3) -> SCLoginAck(4) -> SCStartupInfoNtf(25) -> SCStartupInfoEquipNtf(26) -> SCStartupInfoHeroNtf(27) -> SCStartupInfoEndNtf(28)`

本次捕获已经提供了真实角色启动数据的原始 wire body，并已生成本地映射 fixture `server/data/fixtures/captured-role-local.json`。fixture 使用本地 `sdk_user_id=1`、`login_open_id=1` 映射，不复制原始 `open_id` 或认证 token；原始帧仍保留在受控 pcap 和派生分析文件中。

## 证据标记

- **Confirmed by static analysis（静态分析确认）**：来自反编译程序集、smali、生成的 Protobuf 定义或现有源代码。
- **Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：来自本次 pcap、模拟器 `ss`、logcat 或重组后的帧数据。
- **Inferred and still requiring validation（推断，仍需验证）**：根据运行时现象推导，但缺少 DNS、HTTP 响应或服务端配置的直接证据。

## 抓包范围和环境

本轮使用安装了原版 APK 的模拟器，不清除应用数据，不修改 APK，不修改 YooAsset/HotUpdate 地址。抓包覆盖模拟器上的 TCP 流量，之后只对 `3.0.140.171:21001` 做游戏 TCP 过滤和 TCP sequence 重组。

启动抓包使用的设备命令为：

```text
tcpdump -i any -s 0 -U -w /data/local/tmp/tao-original-20260823-1605.pcap tcp
```

运行步骤：

1. 启动 `tcpdump`。
2. 强制停止并启动 `com.IdolTime.Cards.game18`。
3. 等待原版资源初始化完成。
4. 点击原版入口的“开始游戏”。
5. 等待游戏 TCP 登录、启动消息和后续心跳出现。
6. 停止 `tcpdump`，将 pcap 拉回工作区。

真实游戏服 TCP 三次握手开始于 `2026-08-23 16:06:53.081822`。最后一个目标 TCP 数据包出现在 `2026-08-23 16:07:43.720358`；抓包进程随后停止，未留下运行中的 `tcpdump` 进程。

SDK HTTPS、ThinkingData、`ipconfig.io`、YooAsset/HotUpdate 和其他第三方连接同时存在于总 pcap 中，但本报告的帧统计只包含 `3.0.140.171:21001`。

## 原始和派生证据

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `server/data/captures/tao-original-20260823-1605.pcap` | 原始证据 | 模拟器 `any` 接口的 TCP pcap，大小 `10,028,448` 字节 |
| `server/data/captures/tao-original-20260823-1605-game-tcp-summary.txt` | 派生证据 | `tcpdump -r` 对目标 IP/端口的 TCP 包摘要 |
| `server/data/captures/tao-original-20260823-1605-game-frames.json` | 派生证据 | TCP 重组、10 字节帧头解析和 Protobuf wire body 摘要 |
| `server/data/captures/tao-original-20260823-1605-logcat-filtered.txt` | 运行日志 | 登录、Unity 网络组件和游戏进入流程相关日志 |
| `tools/analyze_game_tcp_pcap.py` | 分析工具 | 只读 pcap，按 TCP sequence 重组并解析游戏帧 |

原始 pcap SHA-256：

```text
B5C255D325AEBF6BDE6668B45F12D085056776E4F9F9EAF46A72F9236C625DD8
```

原始 pcap 包含真实登录认证 token、客户端轨迹和角色数据，不应上传到公开仓库或发送给无关人员。派生 JSON 对客户端登录请求不保存 `body_b64`，只保存登录字段、body 长度和 token 指纹；服务器启动帧仍保留 base64 body，供本地 fixture 校验使用。

## 运行时连接证据

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：模拟器上的 `ss -tnp` 显示：

```text
ESTAB  10.0.2.15:40258  3.0.140.171:21001  users:("me.Cards.game18",pid=31954,fd=100)
```

pcap 中对应的关键包为：

```text
2026-08-23 16:06:53.081822  10.0.2.15:40258 -> 3.0.140.171:21001  SYN
2026-08-23 16:06:53.083691  3.0.140.171:21001 -> 10.0.2.15:40258  SYN/ACK
2026-08-23 16:06:53.177583  10.0.2.15:40258 -> 3.0.140.171:21001  TCP payload 909 bytes
2026-08-23 16:06:53.780445  3.0.140.171:21001 -> 10.0.2.15:40258  TCP payload 28 bytes
```

本次抓包确认的是实际 TCP 目标 IP，不等同于“默认域名解析结果”。同一轮运行后查询到的 `dev.g.idoltime.games` A 记录为 `13.248.212.97`，与实际目标 `3.0.140.171` 不同。

**Inferred and still requiring validation（推断，仍需验证）**：`3.0.140.171` 可能是区服列表或运行时配置返回的地址，而不是 APK 默认 `dev.g.idoltime.games` 的直接 DNS 结果。由于本轮过滤只抓 TCP，没有保存 DNS 和 SDK `/server/list` 的明文响应，不能据此确认地址来源。

## TCP 重组统计

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：

| 方向 | TCP 包数 | TCP payload 字节数 | 重组字节数 | sequence gap |
| --- | ---: | ---: | ---: | ---: |
| 客户端 -> 服务端 | 52 | 2,045 | 2,045 | 0 |
| 服务端 -> 客户端 | 55 | 6,886 | 6,886 | 0 |

TCP 层存在明显分片：服务端启动数据的一部分以 `1440`、`723`、`124` 等 payload 分段到达，但重组后可以按游戏协议完整解析。不能把单个 TCP payload 直接当作一个游戏消息。

游戏帧使用已由静态分析确认的 10 字节大端头：

| 偏移 | 长度 | 类型 | 本次观察 |
| ---: | ---: | --- | --- |
| 0 | 2 | `uint16` | body 长度 |
| 2 | 2 | `uint16` | 消息号 |
| 4 | 4 | `int32` | 帧序号，启动阶段观察到为 `0` |
| 8 | 2 | `uint16` | flag |

客户端第一条游戏帧总长为 `909` 字节，其中 10 字节头和 `899` 字节 `CSLoginReq` body；这与 pcap 中的第一个带 payload 客户端包完全对应。

## 登录请求

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：重组后的消息号 `3` 是一个客户端到服务端帧，body 长度 `899` 字节。按现有 wire-level Protobuf 解码得到：

| 字段 | 实际值或状态 |
| --- | --- |
| `platform` | `18game` |
| `system_type` | `1` |
| `auth_type` | `18game` |
| `open_id` | `<TEST_OPENID>` |
| `account` | `<TEST_ACCOUNT>` |
| `device_code` | 存在，未在本报告展开 |
| `client_track_json` | 存在，包含包名、版本、设备和运行环境字段 |
| `game_version` | `0` |
| `select_zone` | `0` |
| `user_id` | 空字符串 |
| `ip` | 空字符串 |
| `auth_token` | 32 字符 opaque token；只保留长度和 SHA-256 指纹 |

`client_track_json` 中观察到的运行环境包括：包名 `com.IdolTime.Cards.game18`、应用版本 `1.2.3`、Android 15、设备型号 `PHY110`、模拟器标志和区服字段 `4`。该 JSON 是客户端发送的轨迹数据，不应在公共文档中复制完整内容。

## 登录和启动帧

以下是目标 TCP 流中登录阶段的完整已知帧。body 长度来自重组后的游戏帧，不是 TCP 分片长度。

| 时间顺序 | 方向 | 消息号 | 类型 | body 长度 |
| ---: | --- | ---: | --- | ---: |
| 1 | C -> S | `3` | `CSLoginReq` | `899` |
| 2 | S -> C | `7` | `SCHandShakeNtf` | `18` |
| 3 | S -> C | `4` | `SCLoginAck` | `9` |
| 4 | S -> C | `25` | `SCStartupInfoNtf`，基础角色和时间/区服 | `152` |
| 5 | S -> C | `25` | `SCStartupInfoNtf`，背包数据 | `38` |
| 6 | S -> C | `25` | `SCStartupInfoNtf`，风险战斗/图鉴/地址等 | `59` |
| 7 | S -> C | `25` | `SCStartupInfoNtf`，区域任务/通用任务/签到等 | `994` |
| 8 | S -> C | `24176` | 辅助消息 | `4` |
| 9 | S -> C | `26` | `SCStartupInfoEquipNtf` | `2` |
| 10 | S -> C | `27` | `SCStartupInfoHeroNtf` | `114` |
| 11 | S -> C | `376` | 辅助消息 | `116` |
| 12 | S -> C | `28` | `SCStartupInfoEndNtf` | `0` |

消息 `4` 的 body wire 字段解析为 `Error=0` 和非零 `ClientId=29988810766942465`；结合客户端后续进入 `EnterGame_LoginTask`、角色信息和网络状态日志，判定本次登录成功。消息 `28` 到达后，客户端结束登录等待流程并继续发送主界面相关请求。

四个独立的消息 `25` 帧不是 TCP 分片，而是帧头声明的四个完整游戏消息；它们的 body 需要按原始顺序全部保留。后续本地 fixture 不能只提取最大的一帧 `994` 字节。

## 心跳和进入主界面后的流量

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：启动序列后，客户端和服务端持续交换消息号 `1` 和 `2`：

- 客户端消息 `1` 共观察到 5 次，单帧 body 长度 `9`。
- 服务端消息 `2` 共观察到 5 次，单帧 body 长度 `7`。
- 客户端发送时间约为 `16:07:03`、`16:07:13`、`16:07:23`、`16:07:33`、`16:07:43`。

静态 `protoMsgId.cs` 将它们分别命名为 `CsPingReq` 和 `ScPingAck`。因此本次运行同时确认了客户端进入游戏后约 10 秒间隔的心跳行为。

启动后还观察到角色、玩家资料、邮件、排行榜、任务和其他页面相关消息。完整消息号、方向、出现次数、body 长度、body SHA-256 和可复用的服务端 body base64 均记录在派生 JSON 中，不在本报告展开所有未知业务消息。

## 消息号清单

本次目标 TCP 流重组出 70 个游戏帧。除启动序列外，观察到的消息号如下：

```text
C -> S: 1, 3, 23, 59, 61, 166, 170, 327, 349, 368, 370, 374,
       24146
S -> C: 2, 4, 7, 24, 25, 26, 27, 28, 55, 60, 62, 167, 171, 184,
       189, 204, 226, 328, 350, 369, 371, 375, 376, 393, 24147,
       24166, 24176
```

其中 `23/24`、`59/60`、`166/167`、`327/328`、`349/350`、`368/369`、`370/371`、`374/375` 等请求/响应对已经由静态 `protoMsgId.cs` 提供名称；本次报告只对登录、启动和心跳链路作行为结论，不将其他消息的业务字段视为已经完整恢复。

## 对本地服务端恢复工作的影响

此前文档中的“当前工作区没有真实 `4/25/26/27/28` 游戏 TCP 帧”已被本次捕获结果取代。

当前可以确认：

1. 真实服务端接受当前原版账户的 `CSLoginReq(3)`。
2. 服务端返回成功的 `SCLoginAck(4)`。
3. 服务端按顺序发送四个 `SCStartupInfoNtf(25)` body，再发送 `26`、`27` 和 `28`。
4. 客户端收到 `28` 后继续工作，并保持心跳连接。
5. 真实启动数据包含本地伪造 fixture 之前缺失的角色、背包、任务、VIP 和其他扩展字段。

**Inferred and still requiring validation（推断，仍需验证）**：已生成的本地映射 fixture 很可能足以让本地服务端通过第一阶段登录，但是否能在所有页面和角色操作中替代真实服务端，仍需要启动本地服务端后进行实机验证。不能仅凭原版登录成功或 fixture 通过结构校验推断所有后续业务协议都已恢复。

## 后续步骤

1. 以 `server/data/fixtures/captured-lily6985-local.json` 为输入，启动本地服务端并验证 `server/list -> TCP connect -> 3/4 -> 25/25/.../26/27/28 -> 主界面`。
2. 核对本地映射 `login_open_id=1` 与 SDK 测试账号的实际登录身份，不要把原始 `9227573` 或原始 token 自动写入本地账号。
3. 对比本地服务端和本次原版捕获的后续 `23/24`、`59/60`、`166/167`、`327/328` 等请求/响应。
4. 对比本地服务端和本次原版捕获的后续 `23/24`、`59/60`、`166/167`、`327/328` 等请求/响应。
5. 如果本地客户端仍卡在某个页面，按 pcap 中的消息号和 body 差异继续补齐协议；不要把 SDK HTTP、YooAsset/HotUpdate 或 CDN 流量混入游戏 TCP fixture。
