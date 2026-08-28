# 游戏角色状态模型

> **分类**：系统实现 / 状态机与持久化  
> **状态**：已确认 (Confirmed by static analysis & test suite)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

更新时间：2026-08-23

## 状态边界

角色持久化在 `game_roles.game_state_json` 中使用 `schema_version=1`。模型位于 `server/game_state.py`，写入通过 `Storage.merge_game_state()` 使用字段级合并；旧版顶层 `coin`、`diamond`、`level`、`lineup`、`risk`、`guide` 等字段保留为兼容别名，不能覆盖结构化字段的其他内容。

结构化区域如下：

| 区域 | 持久化内容 | 合并语义 |
| --- | --- | --- |
| `role_base` | UID、昵称、签名、性别、等级/经验、金币、钻石、头像、区域、重置时间 | 只更新请求中出现的标量字段 |
| `role_bag` | item id、配置 id、数量、时间戳、下一个 item id | item map 按 id 合并；数量为 0 删除；`wire_dirty` 防止删除后回退 raw blob |
| `equipment` | 英雄装备/装备原始 wire 快照 | 已确认字段结构化，未确认字段保留 wire 快照 |
| `heroes` | 配置 id、等级、阶段、星级、皮肤、装备、技能、好感、状态 | 按英雄配置 id 合并，单英雄字段级更新 |
| `lineups` | 普通编队、战斗编队、编队 map、当前编队 id | 编队数组按操作整体替换，map 按编队 id 合并 |
| `risk_battle` | 当前关卡、解锁关卡、通关星级、首通奖励领取状态 | 关卡 key 合并；奖励操作由 battle receipt 幂等保护 |
| `strength_state` | 当前值、上限、恢复时间、消耗规则 | 只更新出现的字段 |
| `tasks` | 区域、通用、活动、主线任务容器 | 按任务 key 合并 |
| `story` | 阅读记录、条件事件、传输数据、教程 | key/value 合并；教程保留累计完成标记 |
| `gacha` | 卡池、抽卡记录、图鉴、重复英雄计数 | 记录追加由 gacha receipt 保护 |
| `social` | 排行榜、邮件、好友、社区、活动基础信息 | 按已确认业务 key 合并，未知业务字段不伪造 |
| `operations` | battle、gacha、hero_level_up、payment 操作收据 | `namespace + sha256(request body)` 唯一；最多保留 256 条/namespace |

## TCP 读写边界

**Confirmed by static analysis and packet capture or runtime observation**：`25` 是分片的启动聚合消息，已确认 field 4 为 `RoleBase`、field 5 为 `RoleBag`；`26` 为装备启动消息；`27` 为英雄/编队启动消息；`28` 只表示启动结束。启动时从持久化状态生成已确认的 `RoleBase`、`RoleBag` 和 `RoleHero`，其余尚未恢复 schema 的启动字段继续从本地 fixture 保留。

| 消息 | 本地状态边界 |
| --- | --- |
| `3/4` | 认证和启动窗口，不写玩法状态 |
| `25` | 读取/生成 `role_base`、`role_bag`、教程已确认字段；未知字段按原 wire 保留 |
| `26` | 读取/发送 `equipment`；未确认的装备字段保留原 wire |
| `27` | 读取/生成 `heroes`、`lineups` |
| `28` | 启动完成标记，不写玩法状态 |
| `21/22` | `role_base.nickname` 字段级更新 |
| `59/60`、`61/62` | `story.guide` 字段级保存/读取 |
| `109/110`、`111/112` | 普通/战斗编队字段级保存及 ACK |
| `29/30`、`31/32`、`398` | `gacha`、`heroes` 和抽卡操作收据 |
| `93/94`、`118` | `heroes[hero_id]` 和升级操作收据 |
| `141/142`、`143/144`、`149` | 风险战斗会话、奖励、星级和 battle 操作收据 |
| `327/328`、`368/369`、`370/371`、`374/375` | `story.transmit`、`story.read`、`story.conditions` |
| `377/378`、SDK 支付结算 | 游戏订单/支付表幂等；钻石同步到 `role_base` |

**Inferred and still requiring validation**：活动、邮件、好友、排行榜和完整装备业务的 protobuf 字段尚未全部恢复，因此当前只建立持久化容器和边界，不把 fixture 中未知账号数据解析后写入本地状态。

## 幂等规则与测试

- 战斗、抽卡和英雄升级使用请求 body hash 收据；相同业务 body 重放只返回相同结果，不重复发放或升级。
- 支付使用 `game_orders`、`game_diamond_transactions` 的唯一约束和现有结算事务。
- `Storage.merge_game_state()` 在一个 SQLite 写事务内完成字段级合并和版本递增。
- `tests/test_game_state.py` 覆盖 schema 迁移、RoleBag 增改删、英雄/编队启动重建、重复抽卡和重复升级。
- `tests/test_game.py` 覆盖昵称、教程、战斗和服务重连后的状态恢复。

