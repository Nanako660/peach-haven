# 服务端兼容性 TODO

> **分类**：待办路线 / 兼容性规划  
> **状态**：参考指南 (Planning & Roadmap)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

更新时间：2026-08-23

本文记录当前本地 SDK 兼容服务端和游戏 TCP 兼容服务端的未完成工作。内容基于当前工作区代码、2026-08-23 两次游戏 TCP 抓包以及现有自动化测试整理。

## 范围和边界

- 不修改 `桃.apk`。
- 不修改 YooAsset、HotUpdate 或 `pxcdn.jhdwxp.com` 地址。
- SDK HTTP 流量、游戏 TCP 流量、YooAsset/HotUpdate 流量分开记录。
- 原始 pcap 只作为受控本地证据，不复制真实 Token、账号或完整轨迹到普通文档。
- 本文只记录服务端兼容性工作，不把热更新资源镜像工作混入当前阶段。

## 状态标记

- `[x]` 已实现，并有代码或自动化测试证据。
- `[~]` 有最小兼容实现或抓包回放，但不是完整业务实现。
- `[ ]` 尚未实现。
- **Confirmed by static analysis**：由反编译代码、Protobuf 定义或服务端代码直接确认。
- **Confirmed by packet capture or runtime observation**：由 pcap、重组帧、logcat 或运行时数据库直接确认。
- **Inferred and still requiring validation**：根据代码和抓包推断，仍需本地实机验证。

## 当前基线

### 已通过的基础链路

- `[x]` AES-128 ECB 请求和响应封装。
- `[x]` SDK 账号注册、登录、快捷账号、Token 校验和资料更新。
- `[x]` `/server/list` 返回本地游戏 TCP 地址。
- `[x]` 游戏 TCP 10 字节大端头、TCP 分片重组后的帧读写。
- `[x]` `CSLoginReq(3)` 的 OpenId 主匹配和 SDK Token 校验。
- `[x]` 启动 fixture 中的 `7/4/25/26/27/28` 顺序重放。
- `[x]` 现有自动化测试 51 项通过，`compileall` 通过，时间为 2026-08-23。

### 当前实现的本质

当前服务端已经可以把原始抓包转换为本地角色 fixture，并对部分请求使用响应模板回放。它还不是一个完整的独立游戏服务端，主要限制如下：

1. 部分响应依赖 `tao-original-20260823-1605-game-frames.json` 或 `tao-continuous-20260823-174438-game-frames.json`。
2. 只有 `76` 和 `149` 等少数通知会按本地角色状态改写。
3. 英雄、背包、任务、剧情、体力和活动状态没有完整的结构化持久化模型。
4. 现有测试主要验证协议形状、模板回放和最小状态更新，尚未覆盖真实设备完整回归。

## P0：必须优先完成

### P0-1 本地设备端到端验证

- `[x]` 启动 FastAPI 和游戏 TCP 服务端。
- `[x]` 使用本地 SDK 账号完成：
  `server/list -> SDK 登录 -> CSLoginReq(3) -> SCLoginAck(4) -> 25/26/27/28`。
- `[x]` 确认收到 `SCStartupInfoEndNtf(28)` 后能够进入主界面，不只保持 TCP 连接。
- `[x]` 记录本地设备 logcat、TCP trace 和失败时最后一个请求消息号。
- `[x]` 对比本地和原始抓包的消息顺序、body 长度、关键字段和 ACK 等待点。
- `[x]` 断开并重连，确认昵称、教程、英雄、编队、战斗进度和钻石仍然存在。

实机证据：[`../evidence/p0-1-device-e2e-20260823.md`](../evidence/p0-1-device-e2e-20260823.md)。本轮确认的非阻塞差异为本地未发送原始辅助通知 `24176/376`，以及本地动态角色状态导致第一段 `25` body 长度不同；客户端仍成功进入主界面并完成重连。

证据：原始启动抓包确认客户端收到 `28` 后还会继续发送初始化请求，不能只用 fixture 校验成功代替实机验证。参见 [`../analysis/original-game-tcp-capture-20260823.md`](../analysis/original-game-tcp-capture-20260823.md) 和 [`../analysis/game-tcp-capture-analysis-20260823.md`](../analysis/game-tcp-capture-analysis-20260823.md)。

### P0-2 建立完整的角色状态模型

`[x]` 已完成 schema v1、字段级合并、启动重建和重复请求收据。实现记录见 [`../implementation/game-state-model.md`](../implementation/game-state-model.md)。当前状态主要集中在 `game_roles.game_state_json`，但已按下列区域定义并隔离 TCP 读写边界：

- `[x]` `RoleBase`：UID、昵称、性别、等级/累计经验、金币、钻石、头像、区域、重置时间。
- `[x]` `RoleBag`：物品 ID、配置 ID、数量、品质扩展字段、背包变更和删除语义。
- `[x]` 英雄：英雄配置 ID、等级、好感/阶段/星级、皮肤、装备、技能。
- `[x]` 编队：普通编队、战斗编队、空位和编队 ID。
- `[x]` 风险战斗：当前关卡、已通关关卡、星级、首通状态和奖励领取状态。
- `[x]` 体力：当前值、上限、恢复时间和消耗规则。
- `[x]` 任务：区域任务、通用任务、活动任务和主线任务进度。
- `[x]` 剧情：阅读记录、条件事件、传输数据和教程存档。
- `[x]` 抽卡：抽卡池、消耗、抽卡记录、图鉴和重复英雄处理。
- `[x]` 活动/社交：排行榜、邮件、好友、社区和活动基础信息。

实现要求：

- `[x]` 所有状态更新使用明确的字段级合并规则，不用整段原始账号 body 覆盖本地状态。
- `[x]` 所有可重复请求具备幂等规则，尤其是战斗结算、抽卡、升级和支付。
- `[x]` 启动时从持久化状态重建已确认的 `25/26/27/28` 字段；未确认字段保留为原始 wire 快照。
- `[x]` 每个已实现状态变更增加针对断线、重连和重复请求的测试。

### P0-3 风险战斗完整结算

**Confirmed by packet capture or runtime observation**：玩法抓包确认 `1001001` 至 `1001006` 共 6 次战斗，全部经过 `141/142 -> 143/144`，且结算中包含经验、金币、钻石、体力和物品变化。

当前已有最小实现，但仍需完成：

- `[ ]` 保存 `141` 的待开始战斗会话，校验 `143` 必须对应已开始的关卡。
- `[ ]` 校验关卡是否解锁、编队是否合法、体力是否足够、重复结算是否允许。
- `[ ]` 正确解析 `143` 的 `LevelId`、`IsWin`、`IsQuit`、`Star` 和 `BattleTarget`。
- `[ ]` 将奖励配置从 `game_tcp.py` 中的硬编码字典移到可审计配置或 fixture 数据。
- `[ ]` 持久化 `BaseExp`、`HeroExp`、角色等级变化和经验前后值。
- `[ ]` 持久化金币、钻石、体力、风险关卡和星级奖励状态。
- `[ ]` 持久化 `WinSettlement.ItemList` 到 `RoleBag`，处理新增、扣除和数量合并。
- `[ ]` 持久化任务变化，并生成对应任务通知。
- `[ ]` 对重复 `143` 返回幂等结果，不重复发放金币、钻石、经验和物品。
- `[ ]` 支持失败、退出、低星和未完成战斗，不把所有请求当作六关卡首胜。

抓包中出现的相关服务端通知包括：

```text
76    SCRoleBaseInfoNtf
121   SCItemChangeNtf
136   SCGeneralTaskChangeNtf
149   SCRoleRiskBattleNtf
24140 SCRoleRiskStarRewardChangeNtf
24167 SCActivityMonopolyTaskChangeNtf
399   SCRoleStrengthNtf
```

参见 [`../analysis/gameplay-tcp-capture-20260823.md`](../analysis/gameplay-tcp-capture-20260823.md) 的战斗结算表和消息统计。

### P0-4 消除原始账号通知泄漏

当前 `_patch_gameplay_frame()` 只对少数 `76`、`149` 帧进行改写。需要禁止将原始角色的业务状态直接发送给本地角色：

- `[ ]` 为 `118` 英雄通知生成按本地英雄状态构造的 body。
- `[ ]` 为 `121` 背包通知生成按本地物品差异构造的 body。
- `[ ]` 为 `136`、`24167` 任务通知生成本地任务状态。
- `[ ]` 为 `24140` 星级奖励通知生成本地奖励状态。
- `[ ]` 为 `399` 体力通知生成本地当前值和恢复时间。
- `[ ]` 检查 `76` 内嵌 `RoleBase` 之外的字段是否仍含有原始账号数据。
- `[ ]` 对 `30/32/350/24153/24184` 等查询响应进行账号、UID和状态绑定。
- `[ ]` 启动 `25` 和 `27` 时，把本地持久化的英雄、背包、任务和教程覆盖到 fixture body。
- `[ ]` 加入测试：账号 A 的抽卡、升级和战斗结果不能出现在账号 B 的响应中。

这是当前最重要的数据正确性和隔离问题。相关代码见 [`../../server/game_tcp.py`](../../server/game_tcp.py) 的 `_patch_gameplay_frame`、`_send_startup` 和 `_send_gameplay_event`。

### P0-5 支付结果推送到游戏角色

**Confirmed by static analysis and runtime observation**：SDK `spend/create2` 成功只能触发 SDK 的 `PayCallBack`，不能证明游戏角色已经到账。游戏内钻石和背包由游戏 TCP 通知更新。

- `[ ]` 明确六档商品的游戏服奖励模型：钻石、首购奖励、普通礼包和背包物品。
- `[ ]` 将 SDK 游戏订单、游戏角色、支付订单和奖励发放放入同一幂等结算边界。
- `[ ]` 为到账生成 `76` 角色基础信息通知。
- `[ ]` 对普通物品生成 `121` 背包变化通知。
- `[ ]` 对礼包购买生成 `237` `SCGiftBuyNtf`，包含订单号和奖励 map。
- `[ ]` 断线时保留 outbox，重连后只发送未确认的奖励事件。
- `[ ]` 重复支付请求不能重复发放钻石、物品或首购奖励。
- `[ ]` 验证游戏客户端实际收到通知后，钻石和背包 UI 都发生变化。

当前 `game_events` outbox 只发送 `76`，见 [`../../server/game_tcp.py`](../../server/game_tcp.py) 的 `_event_loop`。支付边界证据参见 [`../analysis/client-payment-chain-analysis.md`](../analysis/client-payment-chain-analysis.md)。

## P1：玩法和启动功能完善

### P1-1 启动后初始化请求从回放升级为业务响应

原始启动抓包在 `28` 后继续出现以下请求/响应：

```text
23/24       CSPlayerInfoReq / SCPlayerInfoAck
59/60       CSGuideSaveReq / SCGuideSaveAck
61/62       CSGuideGetReq / SCGuideGetAck
166/167     CSPlayerRankReq / SCPlayerRankAck
170/171     CSMailListReq / SCMailListAck
327/328     CSTransmitDataReq / SCTransmitDataAck
349/350     CSFriendListReq / SCFriendListAck
368/369     CSReadDataLoadReq / SCReadDataLoadAck
370/371     CSReadDataSaveReq / SCReadDataSaveAck
374/375     CSConditionEventReq / SCConditionEventAck
24146/24147 CSChatStateQueryReq / SCChatStateQueryAck
```

当前状态：

- `[~]` 多数请求已有响应模板回放。
- `[~]` `59/60`、`61/62`、`370/371`、`374/375` 有少量本地状态写入。
- `[ ]` `23/24` 不应只返回原始角色资料，应返回当前本地角色。
- `[ ]` `166/167` 不应只返回原始排行榜和 UID，应生成本地排行榜结果。
- `[ ]` `170/171` 需要邮件数据模型和已读/领取/删除状态。
- `[ ]` `349/350` 需要好友数据模型，而不是固定空列表模板。
- `[ ]` `24146/24147` 需要根据当前聊天/邀请状态生成动态结果。
- `[ ]` 启动阶段主动通知 `376/55/184/189/204/226/24166/24176/393` 需要确认是否可以安全使用模板，或改为本地状态构造。
- `[ ]` 移除对完整原始 `response_capture` 的强依赖；无抓包文件时也应保持首屏协议完整。

证据：[`../analysis/game-tcp-capture-analysis-20260823.md`](../analysis/game-tcp-capture-analysis-20260823.md) 的“启动后的首批业务消息”。

### P1-2 心跳、服务器时间和连接恢复

- `[x]` `1/2` 心跳有回放和空 ACK fallback。
- `[~]` 心跳响应依赖抓包模板时，body 不是动态生成。
- `[ ]` 动态生成 `SCGetServerTimeAck(64)` 的服务器时间、时区和时差，不返回固定 `28800`。
- `[ ]` 实现 `CSReconnectReq(5)/SCReconnectAck(6)`，明确断线重连后的身份和状态恢复。
- `[ ]` 测试心跳与业务通知交错时不会提前关闭响应窗口。
- `[ ]` 测试网络断开、重连、重复登录和同一角色多连接的行为。

### P1-3 编队和英雄通知

**Confirmed by packet capture or runtime observation**：`109/110` 共 7 组、`111/112` 共 6 组；编队从 `[10001,0,0]` 变为 `[10001,10002,0]`，每次操作前后都有 `118`。

- `[ ]` 校验 `109` 的 HeroLineup，拒绝不存在的英雄、重复英雄和非法空位。
- `[ ]` 校验 `111` 的 LineupId 是否存在。
- `[ ]` 区分编辑编队和战斗编队，不只保存一个 `lineup` 数组。
- `[ ]` 生成本地 `118`，包括英雄 map、等级和编队，而不是回放原始 body。
- `[ ]` 将编队写入启动数据，重连后仍能恢复。
- `[ ]` 加入空编队、重复请求、非法英雄和跨账号隔离测试。

### P1-4 抽卡

**Confirmed by packet capture or runtime observation**：`29/30` 返回抽卡池 `1/2/5`；`31/32` 的一次单抽得到英雄 `10002`，并伴随 `118/121/339/363/398`。

- `[ ]` 从本地配置生成 `30`，支持抽卡池和消耗信息。
- `[ ]` 校验抽卡池、数量、消耗道具和抽卡次数。
- `[ ]` 用随机或可配置抽卡结果替代固定 `10002`。
- `[ ]` 处理重复英雄、图鉴 `363`、抽卡开启通知 `398` 和声望变化 `339`。
- `[ ]` 扣除抽卡资源并写入背包流水。
- `[ ]` 保存抽卡记录，补齐 `CSGachaConfirmReq(33)` 和 `CSGachaLogsReq(35)` 的需要。
- `[ ]` 抽卡后重连启动 `27` 能看到新英雄。

### P1-5 英雄养成

- `[ ]` `93/94` 校验英雄存在、升级数量、当前等级和资源消耗。
- `[ ]` 实现等级上限、经验不足、资源不足和非法负数处理。
- `[ ]` 更新英雄状态、角色资源和 `RoleBag`。
- `[ ]` 生成本地 `76` 和 `118`，不发送原始账号通知。
- `[ ]` 按协议逐步补齐好感、阶段、星级、皮肤、穿戴装备和技能升级消息。
- `[ ]` 重连时从持久化英雄状态生成 `27`。

### P1-6 剧情、条件和教程

- `[ ]` `327/328` 按 `Opt=1` 读取、`Opt=2` 保存，ACK 同时返回正确 key 和 value。
- `[ ]` 按 key 保存 `hplay_climax_data` 等传输数据，解析并校验 JSON。
- `[ ]` `368/369` 返回当前角色已读剧情记录，而不是固定空 body。
- `[ ]` `370/371` 按 `ChapterId` 和 `ConversationId` 保存幂等记录。
- `[ ]` `374/375` 按 `CondType` 和 `Para` 保存结构化条件状态。
- `[ ]` 启动 `25` 时恢复剧情和条件状态，确保剧情解锁逻辑可读取。
- `[~]` `59/60` 已能把观察到的教程 terminal step 转换为累计完成标记。
- `[ ]` 补齐未识别教程 segment/step 的通用存储，不只保留最后一次记录。

### P1-7 邮件、排行榜、好友、社区和活动

玩法抓包已经出现邮件、排行榜、好友、社区和活动相关流量，但当前主要依赖模板或空 ACK。

- `[ ]` 邮件列表、读取、领取、删除和未读数。
- `[ ]` 排行榜查询、本人排名、刷新时间和奖励状态。
- `[ ]` 好友列表、搜索、申请、处理、删除和在线通知。
- `[ ]` 社区列表 `24152/24153` 的本地数据模型。
- `[ ]` 活动基础信息 `24183/24184` 和活动任务状态。
- `[ ]` 处理 `184/189/204/226/24166/24167/253/260/384` 等主动通知，避免直接发原始账号 body。

## P1：SDK HTTP 接口

### 已有但只是最小兼容的接口

- `[~]` `/api/sdk/system/info`：只返回最小 `GameSystemData`，VIP、任务点、下载和媒体字段仍是默认值。
- `[~]` `/api/sdk/system/gameTrack`：只保存原始 JSON，不解析事件，也不驱动任务或用户状态。
- `[~]` `/api/sdk/UserProduct/getProductList`：返回空商品列表，不能用于完整支付商品展示。
- `[~]` `/api/sdk/Recharge/create`：模拟成功，不创建真实充值业务状态。
- `[~]` `/api/sdk/Recharge/createAndSpend`：模拟成功，不执行完整充值和消费事务。
- `[~]` `/api/sdk/spend/create2`：已支持部分已确认商品和游戏订单，但未知商品仍只记账。
- `[~]` `/api/sdk/login/singleGameVerify`：当前默认按已购买处理，需要确认真实购买资格规则。

### 尚未实现的 SDK 路由

- `[ ]` `/api/sdk/User/bindEmail`
- `[ ]` `/api/sdk/User/password`
- `[ ]` `/api/sdk/User/vipReceiveCoin`
- `[ ]` `/api/sdk/user/kf`
- `[ ]` `/api/sdk/Help/lists`
- `[ ]` `/api/sdk/game/more`
- `[ ]` `/api/sdk/Recharge/history`
- `[ ]` `/api/sdk/TransactionLog/lists`
- `[ ]` `/api/sdk/user/vipLists`
- `[ ]` `/api/sdk/Login/upPass`
- `[ ]` `/api/sdk/Mail/sendVerificationCode`

这些路径来自静态 `ApiService.smali` 分析，当前没有对应 FastAPI 路由。参见 [`../analysis/sdk-network-protocol.md`](../analysis/sdk-network-protocol.md)。

### 已返回但没有对应路由的 URL

- `[ ]` 实现 `/api/sdk/upload`，或在确认 APK 不会调用后移除该广告 URL。
- `[ ]` 确认 `SDK_UPLOAD_IMAGE_URL` 的请求格式、加密方式、返回模型和文件保存边界。

## P2：数据、运维和安全完善

- `[ ]` 为游戏状态增加 SQLite 结构化表或版本化 JSON schema，避免无版本 `game_state_json` 无限扩张。
- `[ ]` 为角色状态更新增加事务日志和来源消息号，便于从 TCP trace 追溯。
- `[ ]` 对支付、抽卡、战斗和奖励事件增加唯一业务幂等键。
- `[ ]` 增加角色多连接策略：踢旧连接、拒绝重复连接或广播状态，三者选定一种并测试。
- `[ ]` 增加 fixture 与原始账号身份的显式映射检查，禁止按账号名猜测角色。
- `[ ]` 对所有模板响应做 UID、OpenId、订单号和资源数扫描，阻止原始敏感数据泄漏。
- `[ ]` 增加异常 body、超长帧、未知消息号、错误 flag 和连接半关闭测试。
- `[ ]` 增加 SQLite 并发写入、服务重启、outbox 重发和重复 ACK 测试。
- `[ ]` 继续记录 SDK API、游戏 TCP、支付回调和 HotUpdate 的不同证据来源。
- `[ ]` 保持原始 pcap、脱敏帧 JSON 和本地 fixture 的权限边界，不把真实 Token 写入 fixture。

## 推荐实施顺序

### 阶段一：先解决数据正确性

1. 完成本地设备端到端登录和首屏验证。
2. 建立英雄、背包、风险战斗、任务、剧情和体力的最小状态模型。
3. 把 `76/118/121/136/149/24140/24167/399` 从模板回放改为本地状态构造。
4. 让战斗结算、抽卡和英雄升级在重连后恢复。

### 阶段二：完成玩法闭环

1. 完成战斗奖励和幂等结算。
2. 完成抽卡资源扣除、英雄生成、图鉴和抽卡记录。
3. 完成编队校验和英雄通知。
4. 完成剧情读取、条件事件和教程通用存储。
5. 实现邮件、排行榜、好友、社区和活动的最小动态模型。

### 阶段三：补齐 SDK 和支付体验

1. 完成商品列表、订单历史和交易记录。
2. 完成支付到账的 `76/121/237` 通知链。
3. 根据实际调用补齐邮箱、验证码、密码、VIP、帮助和客服接口。
4. 完成 upload URL 的调用验证或实现。

## 验收标准

- `[ ]` 新账号能够从 SDK 登录进入游戏主界面。
- `[ ]` 两个账号同时测试时，角色、英雄、背包、任务和剧情状态完全隔离。
- `[ ]` 完成一关战斗后，金币、经验、体力、物品、任务和星级状态在重连后保持一致。
- `[ ]` 抽卡和英雄升级后，客户端 UI 与重连后的启动数据一致。
- `[ ]` 支付成功后，SDK 回调成功，游戏角色钻石/物品也能通过 TCP 通知到账。
- `[ ]` 重复请求、断线重连和服务重启不会重复发放奖励。
- `[ ]` 本地 TCP trace 与协议定义一致，不依赖原始账号的未改写业务 body。
- `[ ]` 运行完整测试：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server tests
python -m server.client
```

## 证据索引

- 原始启动 TCP 抓包：[`../analysis/original-game-tcp-capture-20260823.md`](../analysis/original-game-tcp-capture-20260823.md)
- 启动帧和首屏请求分析：[`../analysis/game-tcp-capture-analysis-20260823.md`](../analysis/game-tcp-capture-analysis-20260823.md)
- 局内外玩法抓包：[`../analysis/gameplay-tcp-capture-20260823.md`](../analysis/gameplay-tcp-capture-20260823.md)
- SDK API 清单：[`../analysis/sdk-network-protocol.md`](../analysis/sdk-network-protocol.md)
- 客户端支付链：[`../analysis/client-payment-chain-analysis.md`](../analysis/client-payment-chain-analysis.md)
- 游戏 TCP 实现：[`../../server/game_tcp.py`](../../server/game_tcp.py)
- SDK HTTP 实现：[`../../server/main.py`](../../server/main.py)
- SQLite 状态和 outbox：[`../../server/storage.py`](../../server/storage.py)
