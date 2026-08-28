# 原版游戏局内外玩法 TCP 抓包分析（2026-08-23）

> **分类**：技术分析 / TCP 玩法协议  
> **状态**：已确认 (Confirmed by packet capture)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 结论摘要

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：本次使用未修改的原版 `com.IdolTime.Cards.game18`，持续抓取真实游戏 TCP 连接，覆盖了局内战斗、战斗结算、局外编队、抽卡、特殊剧情状态和角色养成。

- 抓包设备：`127.0.0.1:7555`，设备型号 `PHY110`。
- 游戏 TCP 目标：`3.0.140.171:21001`。
- 抓包时间：2026-08-23 17:44:38 启动，目标流量最后出现在 17:54:53 左右；下文时间均为中国标准时间（UTC+08:00）。
- TCP 流：单条连续连接，客户端方向 `46,585` bytes，服务端方向 `50,583` bytes，TCP sequence gap 为 `0`。
- 游戏帧：重组 `1,024` 帧；客户端 TCP payload 包 `778` 个，服务端 TCP payload 包 `885` 个。
- 局内战斗：确认 6 次 `1001001` 至 `1001006`，全部上报 `IsWin=1`、`Star=3`。
- 抽卡：确认 1 次 `CSGachaReq(31)`，`GachaId=2`、`GachaNum=1`，返回 `HeroData.Id=10002` 的新英雄数据。
- 特殊剧情：确认 `hplay_climax_data` 的保存请求，`HeroId=10001` 的 `ClimaxCount=1`；同时确认多组剧情阅读进度和条件事件保存。
- 角色养成：确认 `CSHeroLevelUpReq(93)` 对 `HeroId=10002` 提升 `1` 级，随后服务端通知中的该英雄等级为 `2`。

本报告只分析游戏 TCP，不把 SDK HTTPS、YooAsset/HotUpdate、CDN、统计和其他第三方连接混入结论。

## 证据文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `server/data/captures/tao-continuous-20260823-174438.pcap` | 原始证据 | 设备 `any` 接口的原始 pcap，最终大小 `390,832` bytes |
| `server/data/captures/tao-continuous-20260823-174438-game-frames.json` | 派生证据 | 过滤 `3.0.140.171:21001` 后的 TCP 重组游戏帧 |
| `tools/analyze_game_tcp_pcap.py` | 分析工具 | 按 TCP sequence 重组 10 字节游戏帧头并保存 body |
| `.tools/client_decompiled/Model.dll/Serverproto/protoMsgId.cs` | 静态证据 | 消息号到协议名称的映射 |
| `.tools/client_decompiled/Model.dll/Serverproto/CSRiskBatStartReq.cs` | 静态证据 | 战斗开始请求字段 |
| `.tools/client_decompiled/Model.dll/Serverproto/CSRiskBatWinReq.cs` | 静态证据 | 战斗胜利/结算请求字段 |
| `.tools/client_decompiled/Model.dll/Serverproto/SCRiskBatWinAck.cs` | 静态证据 | 结算 ACK 和 `RiskBatSettlement` |
| `.tools/client_decompiled/Model.dll/Serverproto/CSGachaReq.cs` | 静态证据 | 抽卡请求字段 |
| `.tools/client_decompiled/Model.dll/Serverproto/SCGachaAck.cs` | 静态证据 | 抽卡结果 map 字段 |
| `.tools/client_decompiled/Model.dll/IdolGame/ChatDataNextChatExtension.cs` | 静态证据 | `hplay_climax_data` 的读取、保存和英雄剧情计数 |
| `.tools/client_decompiled/View.dll/IdolTime/DialogueComponentSystem.cs` | 静态证据 | 剧情阅读进度调用 `CSReadDataSaveReq(370)` |
| `.tools/client_decompiled/View.dll/IdolGame/ClientConditionReport.cs` | 静态证据 | 条件事件调用 `CSConditionEventReq(374)` |

原始 pcap SHA-256：

```text
6611E29CE7F5B0391DC0478072179FADFAC2E6D4EEFD9CC3F5648BF52DDDC929
```

pcap 和派生帧 JSON 含有真实角色状态、剧情数据和游戏行为轨迹，仍应作为受控本地证据保存，不上传到公开仓库。

## 抓包边界和重组验证

**Confirmed by packet capture or runtime observation**：本轮抓包开始时游戏 TCP 已经建立，因此没有重复出现登录 `3/4/25/26/27/28`。这是一段登录后的玩法操作流，不应被误用为完整登录 fixture。

```text
抓包启动 17:44:38
首个目标游戏帧 17:44:45.954
最后一个目标游戏帧 17:54:53.099
```

解析结果：

| 方向 | TCP payload 包 | payload bytes | 重组 bytes | sequence gap |
| --- | ---: | ---: | ---: | ---: |
| C -> S | 778 | 46,585 | 46,585 | 0 |
| S -> C | 885 | 50,583 | 50,583 | 0 |

持续心跳 `CS_PING_REQ(1) -> SC_PING_ACK(2)` 各出现 `62` 次。心跳不属于下文玩法事件，但证明连接在长时间战斗、剧情和页面切换期间保持有效。

## 玩法时间线

下表只列业务关键帧，帧序号是派生 JSON 中按时间排序的游戏帧序号；TCP 分片序号不能直接当成游戏消息序号。

| 时间 | 操作 | 客户端请求 | 服务端响应/通知 | 抓包结论 |
| --- | --- | --- | --- | --- |
| 17:45:08-17:45:09 | 首次局外编队 | `109`, `111` | `118`, `110`, `118`, `112` | 编队后同步英雄状态，再确认编辑编队和战斗编队 |
| 17:45:09-17:45:32 | 战斗 1 | `141(1001001)`, `143` | `142`, `149`, `144` 及角色/道具通知 | 胜利，3 星，结算 `Error=0` |
| 17:46:09-17:46:40 | 战斗 2 | `109`, `111`, `141(1001002)`, `143` | `142`, `149`, `144` | 胜利，3 星，结算 `Error=0` |
| 17:47:32-17:47:44 | 抽卡 | `29`, `31(GachaId=2,GachaNum=1)` | `30`, `32`, `118`, `363`, `398` | 单抽成功，新增英雄配置 `10002` |
| 17:48:23-17:49:35 | 调整编队并战斗 3 | `109` 两次，`111`, `141(1001003)`, `143` | `110`, `112`, `142`, `149`, `144` | 抽卡后的新英雄进入编队，战斗胜利 |
| 17:50:07-17:50:32 | 战斗 4 | `109`, `111`, `141(1001004)`, `143` | `142`, `149`, `144` | 胜利，3 星 |
| 17:51:39 | 特殊剧情/英雄高潮状态 | `327` | `328` | 保存 `hplay_climax_data`，英雄 `10001` 计数为 `1` |
| 17:52:13-17:52:59 | 战斗 5 | `109`, `111`, `141(1001005)`, `143` | `142`, `149`, `144` | 胜利，3 星 |
| 17:53:16-17:53:59 | 战斗 6 | `109`, `111`, `141(1001006)`, `143` | `142`, `149`, `144` | 胜利，3 星 |
| 17:54:32-17:54:33 | 角色养成 | `93(HeroId=10002,LevelNum=1)` | `94`, `76`, `118` | 英雄 `10002` 等级从 `1` 变为 `2` |

## 局内战斗和战斗结算

### 通用消息链

**Confirmed by packet capture or runtime observation**：6 次战斗都符合以下结构，具体响应之间会穿插状态通知：

```text
CS_HERO_EDIT_LINEUP_REQ(109)
  -> SC_HERO_EDIT_LINEUP_ACK(110)
CS_HERO_BATTLE_LINEUP_REQ(111)
  -> SC_HERO_BATTLE_LINEUP_ACK(112)
CS_RISK_BAT_START_REQ(141)
  -> SC_RISK_BAT_START_ACK(142)
  -> SC_ROLE_RISK_BATTLE_NTF(149)
CS_RISK_BAT_WIN_REQ(143)
  -> 角色、装备、体力、任务和星级状态通知
  -> SC_RISK_BAT_WIN_ACK(144)
```

静态类确认：

- `CSRiskBatStartReq.LevelId` 是 field `1`，类型 `uint`。
- `CSRiskBatWinReq` 的字段为 `LevelId=1`、`IsWin=2`、`IsQuit=3`、`Star=4`、`BattleTarget=5`。
- `SCRiskBatWinAck` 的 field `1` 是 `Error`，field `2` 是 `RiskBatSettlement`。

### 六次战斗请求

| 次数 | 开始时间 | `141.LevelId` | 胜利请求时间 | `143` 核心字段 | `144` 时间 |
| ---: | --- | ---: | --- | --- | --- |
| 1 | 17:45:09.108 | `1001001` | 17:45:31.749 | `IsWin=1, Star=3, BattleTarget` wire bytes=`30 31 33` | 17:45:32.347 |
| 2 | 17:46:10.181 | `1001002` | 17:46:40.293 | `IsWin=1, Star=3, BattleTarget` wire bytes=`30 31 33` | 17:46:40.705 |
| 3 | 17:48:26.808 | `1001003` | 17:49:35.304 | `IsWin=1, Star=3, BattleTarget` wire bytes=`30 31 33` | 17:49:35.918 |
| 4 | 17:50:08.772 | `1001004` | 17:50:32.259 | `IsWin=1, Star=3, BattleTarget` wire bytes=`30 31 33` | 17:50:32.856 |
| 5 | 17:52:14.054 | `1001005` | 17:52:58.987 | `IsWin=1, Star=3, BattleTarget` wire bytes=`30 31 33` | 17:52:59.586 |
| 6 | 17:53:17.472 | `1001006` | 17:53:58.722 | `IsWin=1, Star=3, BattleTarget` wire bytes=`30 31 33` | 17:53:59.317 |

`BattleTarget` 在静态生成类中声明为 packed `RepeatedField<int>`，但这次 wire body 的 field 5 内容是 ASCII 字节 `30 31 33`。当前只确认原始字节和客户端字段类型，不把它强行解释为具体目标语义。

### 结算内容

**Confirmed by packet capture or runtime observation**：6 个 `144` 都未出现 field 1 `Error`，按 Protobuf 默认值为 `0`；嵌套 `RiskBatSettlement.IsWin=1`。`WinSettlement` 中观察到的字段如下，物品 `config_id` 的业务名称尚未从配置表逐一映射：

| 关卡 | 角色等级/累计经验变化 | `BaseExp` | `HeroExp` | Coin | Diamond | Strength | 结算物品 `config_id x num` |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1001001 | Lv1 `60` -> Lv2 `70` | 60 | 39 | 300 | 0 | 4 | `3x39`, `9x1`, `1001x2`, `2x60`, `1x300` |
| 1001002 | Lv2 `70` -> Lv2 `60` | 60 | 38 | 320 | 10 | -6 | `4x10`, `2x60`, `1x320`, `3x38`, `9x1` |
| 1001003 | Lv2 `60` -> Lv3 `120` | 60 | 55 | 340 | 10 | 4 | `1x340`, `3x55`, `9x1`, `4x10`, `2x60` |
| 1001004 | Lv3 `50` -> Lv3 `110` | 60 | 33 | 360 | 10 | -6 | `1x360`, `3x33`, `6x1`, `4x10`, `2x60` |
| 1001005 | Lv3 `110` -> Lv4 `50` | 60 | 57 | 380 | 10 | 4 | `3x57`, `6x1`, `4x10`, `2x60`, `1x380` |
| 1001006 | Lv4 `50` -> Lv4 `110` | 60 | 200 | 400 | 10 | -6 | `3x200`, `12x1`, `4x10`, `2x60`, `1x400` |

其中 `Strength=-6` 是 Protobuf `int` 的负值按 varint 编码后的有符号解释；原始 body 仍保留在派生 JSON 中。

每次结算还会穿插以下通知：

- `SC_ROLE_BASE_INFO_NTF(76)`：角色基础信息、金币、钻石和角色基础结构更新。
- `SC_ROLE_STRENGTH_NTF(399)`：体力或体力时间状态更新。
- `SC_ITEM_CHANGE_NTF(121)`：背包物品变化。
- `SC_ROLE_RISK_BATTLE_NTF(149)`：当前风险战斗关卡和上一关状态变化。
- `SC_ROLE_RISK_STAR_REWARD_CHANGE_NTF(24140)`：星级奖励状态变化。
- `SC_ACTIVITY_MONOPOLY_TASK_CHANGE_NTF(24167)`、`SC_GENERAL_TASK_CHANGE_NTF(136)` 等：任务进度变化。

因此，本地服务端不能只返回空的 `144`。若要支持战斗后的客户端状态，至少需要同时维护角色等级、经验、金币、钻石、体力、背包、风险关卡星级和任务状态。

## 局外编队

### 请求字段

静态类确认：

- `CSHeroEditLineupReq(109)`：field `1` 为 `LineupId`，field `2` 为 `HeroLineup`。
- `HeroLineup` 的 field `1` 是重复英雄 ID 列表。
- `CSHeroBattleLineupReq(111)`：field `1` 为 `LineupId`。

**Confirmed by packet capture or runtime observation**：本轮出现 `109` 共 7 次、`110` 共 7 次，`111` 共 6 次、`112` 共 6 次。`109` 的 `LineupId` 均使用默认值 `0`；`111` 的 body 均为空，即 `LineupId` 使用默认值 `0`。

### 编队变化

| 时间 | `109` field 2 的 `HeroLineup.Lineup` wire 解码 | 说明 |
| --- | --- | --- |
| 17:45:08.172 | `[10001, 0, 0]` | 首次编队，只有初始英雄 `10001` |
| 17:46:09.334 | `[10001, 0, 0]` | 第二场战斗前重新提交相同编队 |
| 17:48:23.640 | `[10001, 10002]` | 抽卡得到 `10002` 后加入编队 |
| 17:48:25.976 | `[10001, 10002, 0]` | 调整空位/编队长度后提交 |
| 17:50:07.938 | `[10001, 10002, 0]` | 战斗 4 前保持双英雄编队 |
| 17:52:13.222 | `[10001, 10002, 0]` | 战斗 5 前保持双英雄编队 |
| 17:53:16.637 | `[10001, 10002, 0]` | 战斗 6 前保持双英雄编队 |

每次成功编辑后，服务端先后发送 `SC_HERO_CHANGE_NTF(118)` 和空 body 的 `SC_HERO_EDIT_LINEUP_ACK(110)`；战斗编队确认同样先发送 `118`，再发送空 body 的 `112`。这说明 `118` 是客户端实际更新英雄/编队状态的主要通知，`110/112` 更像操作成功 ACK。

## 抽卡

### 抽卡配置读取

`CSGachaListReq(29)` 出现 2 次，分别在 17:47:32.149 和 17:48:03.390。对应 `SCGachaListAck(30)` body 长度均为 `12`，包含 3 个 `GachaList` 条目，当前 wire body 只填充了 `GachaId`：

```text
GachaId = 1, 2, 5
```

### 单抽请求和响应

**Confirmed by packet capture or runtime observation**：17:47:44.021 发送：

```text
CSGachaReq(31)
  GachaId = 2
  GachaNum = 1
```

17:47:44.433 收到 `SCGachaAck(32)`，未出现 `Error` field，按默认值为 `0`。按静态 `SCGachaAck` 的 map 定义解码：

- `List` map key `1`：包含 `GachaObj(ConfigId=10002, Num=1)`。
- `List` map key `2`：空列表。
- `Gain` map：key `51`，value `3`。
- `DrawList` map key `1`：同样包含 `ConfigId=10002, Num=1`。
- `DrawList` map key `2`：空列表。

抽卡结果之后紧接着出现：

- `SC_HERO_CHANGE_NTF(118)`，body 中包含英雄 `10001` 和新英雄 `10002`，两者初始等级均为 `1`。
- `SC_BESTIARY_CHANGE_NTF(363)`，body 中出现与 `10001`、`10002` 对应的图鉴条目 key。
- `SC_GACHA_OPEN_NTF(398)`，3 条通知分别包含 gacha ID `3`、`4`、`7`。
- `SC_ITEM_CHANGE_NTF(121)`、`SC_REPUTATION_CHANGE_NTF(339)` 等资源状态通知。

因此可以确认这次抽卡不是只读抽卡列表，而是实际完成了一次消耗和新英雄发放。

## 特殊剧情和剧情状态

### 英雄高潮数据

**Confirmed by packet capture or runtime observation**：17:51:39.522 出现一次 `CSTransmitDataReq(327)`：

```text
Key   = "hplay_climax_data"
Opt   = 2
Value = [{"HeroId":10001,"ClimaxCount":1}]
```

17:51:39.935 收到 `SCTransmitDataAck(328)`，返回同一个 key/value，未出现 `Error` field，按默认值为 `0`。

**Confirmed by static analysis**：`ChatDataNextChatExtension.cs` 将 `hplay_climax_data` 声明为 `HeroClimaxTransmitKey`；`Opt=1` 用于读取，`Opt=2` 用于保存，保存值是英雄 ID 与 `ClimaxCount` 的 JSON 列表。抓包中的 `Opt=2` 和 `HeroId=10001, ClimaxCount=1` 与该实现完全一致。

### 剧情阅读进度和条件事件

**Confirmed by packet capture or runtime observation**：本轮 `CSReadDataSaveReq(370) -> SCReadDataSaveAck(371)` 共 12 组，全部收到空 body ACK；`CSConditionEventReq(374) -> SCConditionEventAck(375)` 也共 12 组，全部收到空 body ACK。`370` 的主要 `ChapterId/ConversationId` 如下：

```text
100 / 100021101
100 / 100021201
100 / 100021202
41001101 / 4100110101
100 / 100031101
100 / 100031201
100 / 100041101
100 / 100041201
100 / 100041202
100 / 100051101
100 / 100051201
100 / 100061201
```

`374` 的 `CondType` 全部为 `52`，参数依次出现 `833`、`2`、`834`、`688`、`3`、`835`、`836`、`4`、`837`、`5`、`6`、`7`。这些请求使用不同的条件参数推进剧情或事件状态，但条件 ID 的业务名称尚未从配置表完成映射。

**Confirmed by static analysis**：`DialogueComponentSystem.cs` 在剧情对话保存时构造 `CSReadDataSaveReq` 并发送消息 `370`；`ClientConditionReport.cs` 使用 `CSConditionEventReq.CondType` 和 `Para` 发送消息 `374`。因此这些流量属于剧情/客户端事件状态，不是战斗结算的隐式重试。

### 教程埋点

本轮还出现 `CSGuideSaveReq(59) -> SCGuideSaveAck(60)` 共 `296` 组。body 中可读到：

- `TutorialForceFirstBattle`：首次战斗教程节点。
- `TutorialOptionalHeroGrowth`：可选英雄养成教程。
- `herogrowth_10002=1`：新英雄 `10002` 的养成教程状态。

这些 59/60 请求是客户端教程和埋点状态保存，不应直接当作剧情业务数据，但可以用来划分用户操作阶段。

## 角色养成

### 明确的英雄升级请求

17:54:32.918 发送：

```text
CSHeroLevelUpReq(93)
  HeroId   = 10002
  LevelNum = 1
```

17:54:33.544 收到空 body 的 `SCHeroLevelUpAck(94)`。在 ACK 前后同时收到 `SC_ROLE_BASE_INFO_NTF(76)` 和 `SC_HERO_CHANGE_NTF(118)`；对最后一条 `118` 的 `HeroData` 解码得到：

```text
HeroData.Id    = 10002
HeroData.Level = 2
```

因此这次是一个完整的“请求 -> 成功 ACK -> 状态通知”养成链，而不是客户端本地单方面修改显示。

### 战斗带来的养成资源变化

六次 `144` 结算还会更新角色累计经验、英雄经验、金币、钻石、体力和物品。特别是：

- 角色等级在战斗 1、3、5 的结算中分别提升到 `2`、`3`、`4`。
- 抽卡后新英雄 `10002` 出现在 `118` 状态通知中，初始等级 `1`。
- 养成请求发生在最后一场战斗结束之后，最终将 `10002` 变为等级 `2`。

## 相关消息统计

以下为本轮与玩法恢复直接相关的消息计数；心跳和大量教程保存不在表中展开。

| 方向 | 消息号 | 静态名称 | 次数 | body 长度 |
| --- | ---: | --- | ---: | --- |
| C -> S | 29 | `CS_GACHA_LIST_REQ` | 2 | 0 |
| C -> S | 31 | `CS_GACHA_REQ` | 1 | 4 |
| C -> S | 93 | `CS_HERO_LEVEL_UP_REQ` | 1 | 5 |
| C -> S | 109 | `CS_HERO_EDIT_LINEUP_REQ` | 7 | 8/9 |
| C -> S | 111 | `CS_HERO_BATTLE_LINEUP_REQ` | 6 | 0 |
| C -> S | 141 | `CS_RISK_BAT_START_REQ` | 6 | 4 |
| C -> S | 143 | `CS_RISK_BAT_WIN_REQ` | 6 | 13 |
| C -> S | 327 | `CS_TRANSMIT_DATA_REQ` | 1 | 57 |
| C -> S | 370 | `CS_READ_DATA_SAVE_REQ` | 12 | 7/11 |
| C -> S | 374 | `CS_CONDITION_EVENT_REQ` | 12 | 5/6 |
| S -> C | 30 | `SC_GACHA_LIST_ACK` | 2 | 12 |
| S -> C | 32 | `SC_GACHA_ACK` | 1 | 44 |
| S -> C | 94 | `SC_HERO_LEVEL_UP_ACK` | 1 | 0 |
| S -> C | 110 | `SC_HERO_EDIT_LINEUP_ACK` | 7 | 0 |
| S -> C | 112 | `SC_HERO_BATTLE_LINEUP_ACK` | 6 | 0 |
| S -> C | 118 | `SC_HERO_CHANGE_NTF` | 15 | 124/234/235 |
| S -> C | 142 | `SC_RISK_BAT_START_ACK` | 6 | 0 |
| S -> C | 144 | `SC_RISK_BAT_WIN_ACK` | 6 | 63/68/69/75/77/81 |
| S -> C | 149 | `SC_ROLE_RISK_BATTLE_NTF` | 12 | 6/10/29 |
| S -> C | 328 | `SC_TRANSMIT_DATA_ACK` | 1 | 55 |
| S -> C | 363 | `SC_BESTIARY_CHANGE_NTF` | 1 | 30 |
| S -> C | 371 | `SC_READ_DATA_SAVE_ACK` | 12 | 0 |
| S -> C | 375 | `SC_CONDITION_EVENT_ACK` | 12 | 0 |
| S -> C | 398 | `SC_GACHA_OPEN_NTF` | 3 | 3 |
| S -> C | 399 | `SC_ROLE_STRENGTH_NTF` | 12 | 6/24 |

## 对本地兼容服务端的影响

### 本地抓包窗口回放修复

**Confirmed by packet capture or runtime observation（已由抓包和本地回放验证）**：连续抓包不是“一条客户端请求紧跟一条服务端响应”。`59/60`、心跳、`63/64` 以及 `374/375` 与 `370/371` 会发生交错；战斗结算 `143` 和 `144` 之间还会出现多条角色、体力、道具和任务通知。服务端现按请求的期望响应号继续扫描，忽略其他已知 ACK，不再因交错客户端请求提前截断；`141` 在 `142` 后保留到 `149`，`143` 必须扫描到 `144`。

**Confirmed by local automated validation（已由本地自动化验证）**：使用 `tao-continuous-20260823-174438-game-frames.json` 回放时，6 个 `143` 请求全部找到 `144`；服务时间请求只返回 `64`；剧情条件链分别返回 `375` 和 `371`，不会把前一个请求的 ACK 重复发送给后一个请求。

**Inferred and still requiring validation（推断，仍需验证）**：当前本地服务端已有部分通用重放能力，但要完整支持本轮玩法，不能只重放登录和启动 fixture。至少需要补齐以下状态模型和请求响应：

1. 风险战斗：`141/142`、`143/144`、`149`、`24140`，并持久化关卡、星级、累计经验、金币、钻石、体力、掉落物和任务变化。
2. 编队：`109/110`、`111/112`，并用 `118` 推送英雄 map 和 lineup 数据。
3. 抽卡：`29/30`、`31/32`，以及抽卡后的 `118`、`363`、`398`、`121` 通知；不能把 `10002` 固定写死到所有账号。
4. 特殊剧情：`327/328` 需要按 key 和 `Opt` 读写 JSON；`370/371` 和 `374/375` 需要持久化剧情阅读与条件事件状态。
5. 角色养成：`93/94` 以及后续 `76/118`，需要校验英雄存在、扣除养成资源并更新等级。

不能仅凭这次真实服务端接受请求，就推断本地服务端已经具备相同的校验、扣费和持久化行为；这些部分仍需本地模拟器回归验证。

## 结论等级

- **Confirmed by packet capture or runtime observation**：单连接和无 sequence gap；6 次 `1001001-1001006` 战斗；全部胜利和 3 星；抽卡 `2/1`；新英雄 `10002`；`hplay_climax_data` 保存；12 组剧情阅读保存；英雄 `10002` 升级到 2 级。
- **Confirmed by static analysis**：消息号名称、字段编号、战斗/抽卡/编队/剧情/养成类的 Protobuf 类型；`hplay_climax_data` 的 `Opt=1/2` 语义；370/374 在客户端剧情流程中的调用位置。
- **Inferred and still requiring validation**：`BattleTarget` 的业务语义；物品 `config_id` 到具体道具名称的映射；`CondType=52` 和参数的剧情业务名称；本地兼容服务端是否能完整复现这些状态变化。
