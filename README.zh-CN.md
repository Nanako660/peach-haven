# Peach Haven

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

<p><b>移动端游戏《蜜桃乌托邦》（Peach Utopia / <code>com.IdolTime.Cards.game18</code>）本地兼容服务端</b></p>

<h2 style="color: #ff3333;">⚠️ 声明 / DISCLAIMER</h2>
<p style="color: #ff4d4f; font-weight: bold; font-size: 1.15em;">
  本项目仅供逆向工程、网络协议分析与 Python 异步服务端架构学习交流参考，不提供且不包含任何商业代码或专有游戏资产（APK/美术/音频等）。严禁将本项目用于任何商业营利或非法用途。<br>
  本项目为阶段性研究成果，不承诺长期维护以及持续更新。
</p>

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Protocol: AES--128--ECB](https://img.shields.io/badge/SDK_Auth-AES--128--ECB-orange.svg)](docs/analysis/sdk-network-protocol.md)
[![Status: Research](https://img.shields.io/badge/Status-Research%20%2F%20Experimental-lightgrey.svg)](#功能支持矩阵)

</div>

> [!CAUTION]
> **免责声明**：本项目属于个人逆向工程与网络通信协议兼容性研究。本仓库**不内置、不提供、不分发**任何原始游戏 APK 二进制或专有资产文件。使用者若需使用客户端 Patch 工具，必须自行提供合法获取的原版安装包。本项目为阶段性研究成果，**不承诺长期维护及持续更新**。

---

## 目录

- [项目简介](#项目简介)
- [核心特性与架构](#核心特性与架构)
- [功能支持矩阵](#功能支持矩阵)
- [项目目录结构](#项目目录结构)
- [环境依赖准备](#环境依赖准备)
- [快速上手指南](#快速上手指南)
  - [1. 安装 Python 依赖](#1-安装-python-依赖)
  - [2. 一键客户端 Patch（可选）](#2-一键客户端-patch可选)
  - [3. 启动本地服务端](#3-启动本地服务端)
  - [4. 服务端管理 CLI](#4-服务端管理-cli)
  - [5. 运行测试套件](#5-运行测试套件)
- [网络协议与设计说明](#网络协议与设计说明)
  - [1. SDK HTTP 协议](#1-sdk-http-协议)
  - [2. 游戏 TCP 私有协议](#2-游戏-tcp-私有协议)
  - [3. 热更新与 CDN 边界](#3-热更新与-cdn-边界)
- [文档全景索引](#文档全景索引)
- [开源许可证](#开源许可证)

---

## 项目简介

**Peach Haven** 是针对 Unity IL2CPP 移动端卡牌游戏《蜜桃乌托邦》（*Peach Utopia*）研发的本地化兼容服务套件。项目通过反编译逆向与抓包分析，还原了游戏的 SDK 认证协议与底层 TCP 游戏交互协议，并提供了能够完全在局域网/单机离线环境下运行的 Python 双服务（HTTP + TCP）以及自动化客户端补丁工具。

---

## 核心特性与架构

系统由三个主要部分协同工作：

```
+-------------------------------------------------------------+
|                      Peach Haven 架构                       |
+-------------------------------------------------------------+
|                                                             |
|  +---------------------+        +------------------------+  |
|  |  HTTP SDK Server    |        |    Game TCP Server     |  |
|  |  (FastAPI @ 8080)   |        |  (AsyncIO @ 21001)     |  |
|  +----------+----------+        +-----------+------------+  |
|             |                               |               |
|             | AES-128-ECB 登录/Token/订单   | 10-Byte 二进制|
|             | 域名列表分发 & 模拟充值       | 启动/关卡/抽卡|
|             v                               v               |
|  +-------------------------------------------------------+  |
|  |          SQLite 数据持久化 (server/data/app.db)        |  |
|  |   - 用户账号/密码哈希(PBKDF2)   - 钱包G点/订单明细    |  |
|  |   - 玩家角色状态(等级/金币/体力) - 背包道具/阵容编队   |  |
|  +-------------------------------------------------------+  |
|                                                             |
|  +-------------------------------------------------------+  |
|  |        Local Relay APK Patch Pipeline (patch.ps1)     |  |
|  |   - 域名静态收敛至 127.0.0.1:8080                         |  |
|  |   - 注入 classes3.dex 悬浮调试窗与生命周期修复           |  |
|  +-------------------------------------------------------+  |
+-------------------------------------------------------------+
```

1. **HTTP SDK 兼容服务端 (`FastAPI @ 0.0.0.0:8080`)**：
   - 完整模拟游戏 SDK 的 AES-128-ECB 加密通信协议。
   - 提供账号注册、登录、快速账号、Token 校验、版本与维护状态检测、服务器列表分发。
   - 内置模拟充值与 G 点钱包管理，支持开发测试模式下的自动充值。
2. **游戏 TCP 兼容服务端 (`AsyncIO @ 0.0.0.0:21001`)**：
   - 完整解析 10 字节大端协议头与大包分片重组。
   - 支持客户端握手与启动帧序列（`3/4/25/26/27/28`）交互。
   - 基于 SQLite 的角色状态持久化，支持动态金币、体力、队伍编队、背包道具变更与抽卡流程。
3. **客户端 Relay Patch 工具 (`patch.ps1`)**：
   - 自动化反编译、修改 SDK 域名指向本地 `127.0.0.1:8080`、注入悬浮配置窗与 Dex 扩展，一键完成对齐与重签名。
4. **统一命令行管理工具 (`server.cli` / `manage.ps1`)**：
   - 提供服务启停监控、健康检查、日志查看、账号密码管理、钱包点数增扣与抓包数据导入。

---

## 功能支持矩阵

| 模块 | 功能 / 协议接口 | 状态 | 说明 |
| :--- | :--- | :---: | :--- |
| **SDK 认证** | 账号注册 / 密码登录 (`/api/sdk/Login/*`) | ✅ 完整支持 | PBKDF2 哈希存储，支持重名校验 |
| **SDK 认证** | 游客快捷登录 / Token 校验 (`validateToken`) | ✅ 完整支持 | 支持 Session Token 签发与过期管理 |
| **SDK 认证** | 单游戏验证 (`singleGameVerify`) | ✅ 完整支持 | 为进入游戏分配安全凭证 |
| **SDK 业务** | 客户端打点 (`system/gameTrack`) | ✅ 完整支持 | 支持打点数据入库与行为分析 |
| **SDK 账务** | 模拟充值与商品消费 (`spend/create2`) | ✅ 完整支持 | 支持测试环境下自动补足 G 点并核销订单 |
| **游戏服务** | 协议头解包与 TCP 分包重组 | ✅ 完整支持 | 10 字节大端头，支持异步高并发粘包处理 |
| **游戏服务** | 登录与启动初始化 (`3 -> 4 -> 25/26/27/28`) | ✅ 完整支持 | 支持真实客户端从选服到成功进入游戏主城 |
| **游戏服务** | 角色基础属性（体力/金币/钻石/等级） | ✅ 完整支持 | 本地持久化并动态同步客户端显示 |
| **游戏服务** | 英雄与阵容编队 (`lineup`) | ✅ 完整支持 | 支持默认英雄阵容与编队保存 |
| **游戏服务** | 背包系统 (`bag delta`) | ✅ 完整支持 | 支持道具的新增、数量修改与消耗删除 |
| **游戏服务** | 抽卡获取 | 🟡 基础支持 | 支持抽卡协议交互，随机掉落算法持续完善中 |
| **游戏服务** | 关卡战斗与掉落结算 | 🟡 基础支持 | 支持关卡进度记录，结算掉落规则持续完善中 |
| **客户端工具** | APK 一键 Patch 与重打包签名 | ✅ 完整支持 | `patch.ps1` 交互式或命令行一键处理 |
| **资产与热更** | YooAsset / HotUpdate 资产分发 | ⏸️ 保持原站 | 遵循隔离决策，热更新流量不经本地劫持 |

---

## 项目目录结构

```text
peach-haven/
├── server/                     # Python 本地服务端源码
│   ├── main.py                 # HTTP SDK (FastAPI) 服务入口
│   ├── game_tcp.py             # 游戏 TCP (AsyncIO) 服务入口
│   ├── game_proto.py           # 游戏 TCP 协议打包与解包
│   ├── game_state.py           # 游戏状态持久化与状态机模型
│   ├── crypto.py               # SDK AES-128-ECB 加解密模块
│   ├── storage.py              # SQLite 数据库存储层
│   ├── products.py             # 商品与支付映射
│   ├── startup_template.py     # 游戏启动帧模板
│   ├── cli.py                  # 命令行管理入口
│   ├── client.py               # 冒烟测试客户端
│   └── config.toml.example     # 服务端配置模板
├── tools/                      # 辅助工具集
│   ├── apk-relay/              # Relay APK 补丁脚本与 Java 源码
│   ├── analyze_game_tcp_pcap.py # TCP 抓包解析脚本
│   └── recover_game_tcp_protocol.py # 协议自动恢复工具
├── docs/                       # 详尽的技术逆向与实现文档
│   ├── README.md               # 文档索引目录
│   ├── analysis/               # 静态反编译与协议抓包深度分析
│   ├── implementation/         # 服务端与客户端补丁设计实现
│   ├── decisions/              # 阶段性技术决策记录 (ADR)
│   ├── evidence/               # 端到端实机验证与测试记录
│   └── todo/                   # 兼容性待办清单与标准
├── tests/                      # 单元测试与回归测试套件
├── patch.ps1                   # 客户端一键 Patch 脚本
├── start.ps1                   # 服务端一键启动脚本 (后台 HTTP+TCP)
├── stop.ps1                    # 服务端一键停止脚本
├── manage.ps1                  # 服务端管理 CLI 快捷调用脚本
├── requirements.txt            # Python 依赖清单
├── LICENSE                     # GNU General Public License v3.0
├── TODO.md                     # 待办与路线图
├── README.zh-CN.md             # 中文说明文档
└── README.md                   # 英文说明文档
```

---

## 环境依赖准备

运行本项目需要以下环境：

1. **操作系统**：Windows 10/11 或 Linux / macOS（PowerShell 7+ / Bash）。
2. **Python**：Python 3.10 及以上版本。
3. **Java JDK**（仅使用客户端 Patch 工具时需要）：JDK 11 或 JDK 17。
4. **Android SDK 构建工具**（仅使用客户端 Patch 工具时需要）：`d8`、`zipalign`、`apksigner`（或将其放入环境变量/`.tools` 目录）。

---

## 快速上手指南

### 1. 安装 Python 依赖

推荐使用 Python 虚拟环境以隔离依赖：

```powershell
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境 (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# 或 Linux / macOS:
# source .venv/bin/activate

# 安装服务端依赖
pip install -r requirements.txt
```

### 2. 一键客户端 Patch（可选）

> 如需在安卓设备或模拟器上连接本地服务端，需要对原始 APK 应用补丁以重定向域名。

准备好您合法拥有的原版游戏 APK：

```powershell
# 交互式运行：按提示输入原版 APK 路径
.\patch.ps1

# 或直接通过参数指定原包相对/绝对路径
.\patch.ps1 -Apk ".\com.IdolTime.Cards.game18.apk"

# 强制清理缓存并重新解码
.\patch.ps1 -Clean -Apk ".\com.IdolTime.Cards.game18.apk"
```

构建成功后，签名的安装包将生成在 `dist/com.IdolTime.Cards.game18-local-relay-v3.apk`，可直接安装至模拟器或真机。

### 3. 启动本地服务端

使用根目录的一键管理脚本启动双服务（HTTP 8080 + TCP 21001）：

```powershell
# 一键启动服务并在后台运行
.\start.ps1
```

控制台将打印局域网访问地址。若需单独在前台调试运行各服务：

```powershell
# 启动 HTTP SDK 服务
python -m server.main

# 启动 游戏 TCP 服务
python -m server.game_tcp
```

### 4. 服务端管理 CLI

通过 `manage.ps1` 或 `python -m server.cli` 能够轻松管理本地服务器：

```powershell
# 查看服务端运行状态与端口占用
.\manage.ps1 status

# 检查 HTTP 与 TCP 服务健康度
.\manage.ps1 health

# 实时查看服务端日志
.\manage.ps1 logs

# 账号管理：列出所有注册用户
.\manage.ps1 account list

# 账号管理：手动创建测试用户
.\manage.ps1 account create test test1234

# 钱包管理：为指定用户充值 G 点（用于游戏内模拟购买）
.\manage.ps1 account credit test 10000

# 停止服务端
.\stop.ps1
```

默认内置的测试账号为：`test` / `test1234`。

### 5. 运行测试套件

执行完整的 60+ 项单元测试，校验协议解密、状态机模型与支付逻辑：

```powershell
# 运行单元测试
python -m unittest discover -s tests -v

# 运行独立 Python 客户端端到端冒烟测试
python -m server.client
```

---

## 网络协议与设计说明

### 1. SDK HTTP 协议

- **通信加密**：采用 AES-128-ECB 模式，密文使用 PKCS7 填充并经过 Base64 编码。
- **请求解包**：客户端请求体为纯密文字符串，解密后为包含 `device_id`、`token`、`timestamp` 等字段的 JSON 对象。
- **详细规范**：参见 [`docs/analysis/sdk-network-protocol.md`](docs/analysis/sdk-network-protocol.md)。

### 2. 游戏 TCP 私有协议

- **数据帧格式**：
  ```
  +-------------------+-------------------+-------------------+-------------------+------------------------+
  |  TotalLen (4B BE) |   MsgId (2B BE)   |   SeqId (4B BE)   |   Reserved (2B)   |   Protobuf / Body...   |
  +-------------------+-------------------+-------------------+-------------------+------------------------+
  ```
- **核心握手**：
  - `CSLoginReq (MsgId=3)`：客户端附带 SDK Token 发起登录请求。
  - `SCLoginAck (MsgId=4)`：服务端响应登录凭证及角色基础元数据。
  - `SCStartupInfo (MsgId=25~27)`：下发角色养成数据、编队信息与活动状态。
  - `SCStartupInfoEndNtf (MsgId=28)`：告知客户端初始化数据同步完成，允许进入主界面。
- **详细规范**：参见 [`docs/analysis/recovered-game-tcp-protocol.md`](docs/analysis/recovered-game-tcp-protocol.md)。

### 3. 热更新与 CDN 边界

抓包确认的原厂热更新域名为 `pxcdn.jhdwxp.com`。根据技术架构决策，**热更新服务保留原站通道**，本地服务端仅承载认证、账号、状态和局内逻辑，避免因缺失全量热更资源而导致客户端校验阻断。详见 [`docs/decisions/001-local-sdk-original-hotupdate.md`](docs/decisions/001-local-sdk-original-hotupdate.md)。

---

## 文档全景索引

本项目包含详尽的逆向分析过程、协议数据结构与实机验证记录，欢迎查阅：

| 类别 | 文档名称 | 描述 |
| :--- | :--- | :--- |
| **概览** | [`docs/README.md`](docs/README.md) | 全局文档索引与分析结论摘要 |
| **静态分析** | [`docs/analysis/apk-overview.md`](docs/analysis/apk-overview.md) | APK 架构、Unity IL2CPP、Assembly 与资源结构分析 |
| **协议逆向** | [`docs/analysis/sdk-network-protocol.md`](docs/analysis/sdk-network-protocol.md) | SDK HTTP 接口定义与 AES 加密算法实现 |
| **协议逆向** | [`docs/analysis/sdk-domain-manager.md`](docs/analysis/sdk-domain-manager.md) | 客户端域名解析管理、缓存机制与回退策略 |
| **协议逆向** | [`docs/analysis/client-payment-chain-analysis.md`](docs/analysis/client-payment-chain-analysis.md) | 支付、G 点钱包及游戏内商品发放全链路 |
| **TCP 分析** | [`docs/analysis/game-tcp-capture-analysis-20260823.md`](docs/analysis/game-tcp-capture-analysis-20260823.md) | 真实客户端 TCP 启动序列抓包重组与分析 |
| **TCP 分析** | [`docs/analysis/gameplay-tcp-capture-20260823.md`](docs/analysis/gameplay-tcp-capture-20260823.md) | 局内战斗、关卡结算、编队与抽卡抓包分析 |
| **TCP 分析** | [`docs/analysis/recovered-game-tcp-protocol.md`](docs/analysis/recovered-game-tcp-protocol.md) | 恢复出的 TCP 协议结构与 Message ID 映射 |
| **实现设计** | [`docs/implementation/local-server.md`](docs/implementation/local-server.md) | Python 服务端分层架构与 SQLite 存储设计 |
| **实现设计** | [`docs/implementation/game-state-model.md`](docs/implementation/game-state-model.md) | 游戏状态机模型与增量同步机制 |
| **实现设计** | [`docs/implementation/local-relay-apk.md`](docs/implementation/local-relay-apk.md) | Relay APK 补丁方案与 classes3.dex 注入原理 |
| **工具链** | [`tools/README.zh-CN.md`](tools/README.zh-CN.md) | 工具链全景索引与第三方开源上游仓库对照表 |
| **客户端工具** | [`tools/apk-relay/README.md`](tools/apk-relay/README.md) | APK Patch 自动化流水线工具源码说明 |
| **决策记录** | [`docs/decisions/001-local-sdk-original-hotupdate.md`](docs/decisions/001-local-sdk-original-hotupdate.md) | 阶段性架构决策：本地 SDK + 原厂热更分流 |
| **实机验证** | [`docs/evidence/p0-1-device-e2e-20260823.md`](docs/evidence/p0-1-device-e2e-20260823.md) | 模拟器/真机完整端到端链路启动测试报告 |
| **待办路线** | [`docs/todo/server-compatibility-todo.md`](docs/todo/server-compatibility-todo.md) | 服务端未完成功能明细与优先级规划 |

---

## 开源许可证

本项目依据 **[GNU General Public License v3.0 (GPL-3.0)](LICENSE)** 协议开源。

- 本项目代码仅限用于计算机安全、网络协议研究与学术交流用途。
- 严禁将本项目代码用于任何商业运营、私服架设或牟利行为。
- 因非合规使用本项目产生的一切后果由使用者自行承担，与本项目贡献者无关。
