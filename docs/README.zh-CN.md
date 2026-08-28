# Peach Haven 技术分析与实现文档

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

</div>

本目录收录了关于移动端游戏《蜜桃乌托邦》（*Peach Utopia*，包名 `com.IdolTime.Cards.game18`）的逆向工程分析、网络协议恢复、抓包取证、Peach Haven 本地 Python 服务端实现与阶段性架构决策记录。

---

## 📚 文档分类索引

### 1. 静态反编译与资源分析 (Analysis)

- [`analysis/apk-overview.md`](analysis/apk-overview.md)：APK 结构、Unity IL2CPP 架构、Assembly 组织及 YooAsset 资产分析
- [`analysis/apk-modification-feasibility.md`](analysis/apk-modification-feasibility.md)：APK 修改与重打包可行性评估报告
- [`analysis/files-resource-analysis.md`](analysis/files-resource-analysis.md)：客户端本地缓存数据与资源目录结构解析

### 2. 网络协议与认证逆向 (Protocols)

- [`analysis/sdk-network-protocol.md`](analysis/sdk-network-protocol.md)：SDK HTTP 接口协议、AES-128-ECB 加密机制与数据响应模型
- [`analysis/sdk-domain-manager.md`](analysis/sdk-domain-manager.md)：SDK 域名缓存管理、内置服务器列表与回退机制
- [`analysis/client-payment-chain-analysis.md`](analysis/client-payment-chain-analysis.md)：客户端支付回调、G 点虚拟钱包与游戏订单结算链路
- [`analysis/hot-update-yooasset.md`](analysis/hot-update-yooasset.md)：YooAsset 热更新流程、CDN 域名与资源清单规则

### 3. TCP 协议捕获与协议恢复 (TCP & Traffic)

- [`analysis/original-game-tcp-capture-20260823.md`](analysis/original-game-tcp-capture-20260823.md)：原厂服务器 TCP 抓包、TCP 流重组与登录字段结构
- [`analysis/game-tcp-capture-analysis-20260823.md`](analysis/game-tcp-capture-analysis-20260823.md)：原版游戏 TCP 启动帧序列分析（3/4/25/26/27/28）与 Fixture 提取
- [`analysis/gameplay-tcp-capture-20260823.md`](analysis/gameplay-tcp-capture-20260823.md)：局内战斗、结算、编队、抽卡与角色养成交互协议抓包
- [`analysis/recovered-game-tcp-protocol.md`](analysis/recovered-game-tcp-protocol.md)：已恢复的游戏 TCP 协议头定义与 Message ID 映射表
- [`analysis/recovered-game-tcp-protocol.json`](analysis/recovered-game-tcp-protocol.json)：结构化的 TCP 协议 JSON 定义文件

### 4. 系统实现与架构设计 (Implementation)

- [`implementation/local-server.md`](implementation/local-server.md)：Python 本地服务端分层架构、FastAPI / AsyncIO 实现与 SQLite 数据持久化
- [`implementation/game-state-model.md`](implementation/game-state-model.md)：游戏角色状态机模型、背包增量更新（Bag Delta）与幂等操作设计
- [`implementation/local-relay-apk.md`](implementation/local-relay-apk.md)：Relay APK 客户端补丁原理、classes3.dex 注入与域名重定向流水线
- [`../tools/README.zh-CN.md`](../tools/README.zh-CN.md)：项目工具链全景与第三方开源上游仓库索引
- [`../tools/apk-relay/README.zh-CN.md`](../tools/apk-relay/README.zh-CN.md)：客户端双通道中继注入补丁源码与流水线说明

### 5. 架构决策记录 (ADR)

- [`decisions/001-local-sdk-original-hotupdate.md`](decisions/001-local-sdk-original-hotupdate.md)：阶段性技术决策：本地 SDK 兼容服务端 + 保留原厂热更新 CDN 流量隔离

### 6. 实机测试与证据链 (Evidence)

- [`evidence/artifacts.md`](evidence/artifacts.md)：逆向分析过程中的证据文件与产物索引清单
- [`evidence/p0-1-device-e2e-20260823.md`](evidence/p0-1-device-e2e-20260823.md)：Android 模拟器与真机全链路端到端启动验收报告

### 7. 路线图与待办规划 (Roadmap)

- [`todo/server-compatibility-todo.md`](todo/server-compatibility-todo.md)：服务端未完成功能详细清单、优先级与验收标准

---

## 🔍 证据置信度规范

项目文档中的所有逆向结论均遵循以下置信度分级：

- **已确认 (Confirmed)**：经由静态反编译源码、自动化单元测试或 Wireshark 抓包直接验证。
- **推断 (Inferred)**：根据调用上下文、数据结构命名逻辑推导，已具备基础代码但需进一步验证。
- **待验证 (Pending)**：缺少完整网络请求、响应样本或特定场景运行环境的数据。
