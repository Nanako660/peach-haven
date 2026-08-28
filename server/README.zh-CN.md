# 局域网 SDK 兼容服务端

<div align="center">

[English](README.md) | [简体中文](README.zh-CN.md)

</div>

> **分类**：系统实现 / Python 服务端指南  
> **状态**：已确认 (Confirmed by automated tests)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

这是针对 APK SDK 登录链路的第一版 FastAPI 兼容服务端。它不修改 APK，也不接管 YooAsset/HotUpdate 热更新。

## 启动

在包含 `server` 文件夹的工程根目录执行。

### 一键启动 / 管理（推荐）

```powershell
.\start.ps1                       # 同时启动 HTTP(8080) + 游戏 TCP(21001)，打印局域网地址
.\stop.ps1                        # 一键停止
python -m server.cli status       # 状态
python -m server.cli health       # 健康检查
python -m server.cli logs         # 日志（--service http|game|all，-f 跟随）
python -m server.cli lan          # 局域网地址
python -m server.cli account list # 账号列表
python -m server.cli account create <用户名> <密码>
python -m server.cli account password <用户名> <新密码>
python -m server.cli account credit <用户名> <G点数>
python -m server.cli account balance <用户名>
python -m server.cli fixture ...  # 透传 fixture_tool
python -m server.cli smoke        # 冒烟测试
python -m server.cli test         # 单元测试
```

`start` 支持 `--http-port` / `--tcp-port` / `--config`，以及 `--foreground`（HTTP 前台调试）。子进程输出与 PID 文件写入 `server/data`。

### 手动分终端启动（调试用）

```powershell
python -m server.main

# 另开一个终端启动游戏 TCP 服务
python -m server.game_tcp

# 可选：显式指定原版玩法抓包，用于当前已确认的战斗/抽卡/养成响应
python -m server.game_tcp --gameplay-capture .\server\data\captures\tao-continuous-20260823-174438-game-frames.json
```

确认当前目录正确：

```powershell
Test-Path .\server\main.py
```

停止服务：在运行窗口按 `Ctrl+C`。

检查端口：

```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen
```

如果端口被本服务旧进程占用，先确认进程后停止：

```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object OwningProcess
Stop-Process -Id <PID>
```

## 健康检查

```powershell
Invoke-WebRequest http://127.0.0.1:8080/healthz
```

局域网设备访问运行服务端电脑的 IPv4 地址，例如：

```text
http://192.168.1.100:8080/healthz
```

## 接口

所有 SDK `POST` 请求都要求请求体为 AES 密文；`/healthz` 是唯一未加密的检查接口。

| 方法 | 路径 | 当前行为 |
| --- | --- | --- |
| GET | `/healthz` | 返回服务状态 |
| POST | `/server/list` | 返回本地游戏 TCP 区服地址，使用普通 JSON |
| POST | `/api/domain` | 返回本地 SDK 域名候选，兼容普通 JSON 和 AES 请求 |
| POST | `/resource/url` | 返回原始热更新/CDN 根地址，不主动访问该地址 |
| POST | `/api/sdk/Login/account` | 用户名密码登录并签发 Token |
| POST | `/api/sdk/Login/username` | 创建账号并签发 Token |
| POST | `/api/sdk/Login/quickAccount` | 创建随机快捷账号 |
| POST | `/api/sdk/user/validateToken` | 校验 Token，成功返回 `data=true` |
| POST | `/api/sdk/User/doUpdate` | 持久化昵称、性别、头像等资料 |
| POST | `/api/sdk/system/info` | 返回最小 `GameSystemData` 和 `UserData` |
| POST | `/api/sdk/system/gameTrack` | 校验 Token 并记录原始游戏轨迹数据 |
| POST | `/api/sdk/UserProduct/getProductList` | 返回空商品列表，供本地支付页面兼容 |
| POST | `/api/sdk/Recharge/create` | 返回本地模拟充值创建成功，不发起真实支付 |
| POST | `/api/sdk/Recharge/createAndSpend` | 返回本地模拟充值/消费成功 |
| POST | `/api/sdk/spend/create2` | 优先结算已登记的游戏订单并增加角色钻石；无游戏订单时保持旧 G 点兼容路径 |
| POST | `/api/sdk/login/singleGameVerify` | 支持已有 Token 或登录前用户名密码校验 |

其他从 APK `ApiService.smali` 恢复出的 SDK 接口目前仅完成分析，尚未实现，详见 [`../docs/analysis/sdk-network-protocol.md`](../docs/analysis/sdk-network-protocol.md)。

## 加密协议

- 算法：AES-128 ECB
- Padding：PKCS5/PKCS7
- 密钥：`f237311e06398eac`
- 请求媒体类型：`application/octet-stream`
- 请求明文外层结构：

```json
{
  "token": "",
  "deviceId": "device-id",
  "data": {
    "username": "test",
    "password": "test1234"
  }
}
```

响应同样是 AES 密文，明文结构为：

```json
{
  "status": "y",
  "time": "unix_timestamp",
  "errorCode": "",
  "error": "",
  "data": {}
}
```

无效或过期 Token 返回 `status="n"` 和 `errorCode="2002"`。

## 数据与配置

- 默认配置：`server/config.toml`（本地文件，不提交 Git）
- 配置模板：`server/config.toml.example`
- SQLite：`server/data/server.sqlite3`
- 应用日志：`server/data/server.log`
- 游戏 TCP 日志：`server/data/game_tcp.log`
- 启动状态 fixture：`server/data/fixtures/*.json`
- 启动模板：`server/data/startup_template.json`（可选，用 `python -m server.startup_template` 生成）
- Uvicorn 输出：`server/data/uvicorn.stdout.log`、`server/data/uvicorn.stderr.log`
- AES 依赖：`.tools/server_deps`
- pip 缓存：`.cache/pip`
- 初始账号：`test / test1234`
- 密码存储：PBKDF2-HMAC-SHA256，不保存可逆明文密码
- Token：随机不透明字符串，包含创建时间和过期时间
- 游戏轨迹：保存在 `game_tracks` 表中，记录用户 ID、设备 ID、原始 JSON 和接收时间
- 本地支付模拟：不连接真实支付平台，也不访问 `notifyUrl`。已确认的六档商品会按 G 点价格扣款并写入发放记录；未知金额仍只记账
- G 点钱包：保存在 `wallet_accounts`，变更记录保存在 `wallet_transactions`。默认开启 `spend/create2` 自动补充本次商品所需 G 点，流水类型为 `auto_credit`；关闭后余额不足返回 `status="n"`、`errorCode="2003"`
- 商品发放：保存在 `product_grants`，首购按商品列表的“首冲双倍”记录额外数量；这不会修改 APK 或直接改写 Unity 客户端库存
- 支付订单：保存在 `payment_orders` 表；成功订单为 `completed`，余额不足为 `insufficient_balance`，重复请求保持幂等
- 游戏角色、玩法状态、游戏订单、钻石流水和在线更新 outbox 分别保存在 `game_roles`、`game_orders`、`game_diamond_transactions` 和 `game_events` 表；玩法状态位于 `game_roles.game_state_json`

## 游戏 TCP 与启动 fixture

TCP 头部为 10 字节：大端 `bodyLen(uint16) + msgId(uint16) + seq(int32) + flag(uint16)`。
当前 TCP 服务还覆盖本地抓包确认的编队、风险战斗开始/结算、抽卡、英雄升级、昵称、剧情阅读、条件事件、个人资料、社区和活动基础查询。`GAME_PLAY_CAPTURE` 或 `--gameplay-capture` 指向玩法抓包时，服务端会按请求业务字段选择对应响应和状态通知；未匹配时使用本地兼容 ACK。六档商品的 `ItemID=4` 通过 `RoleBase.Diamond` 发放，不使用背包增量消息。

服务端不会猜测角色账号。fixture 必须包含 `sdk_user_id`、`server_id`、`login_open_id` 或兼容旧字段 `login_user_id`，以及消息号 `4/25/26/27/28`；如果捕获到 `7`，服务端会在 `4` 前保留并重放。`OpenId` 是当前 APK 的主登录身份；只有没有 `OpenId` 的旧请求才按 `UserId` 匹配。启动序列必须组合包含完整 `RoleBase` 和 `RoleBag`；真实服务端可能连续发送多个部分更新的消息 25，服务端会保留原始顺序并合并校验。可使用 JSON 帧转储导入：

```powershell
python -m server.fixture_tool validate .\capture.json
python -m server.fixture_tool install .\capture.json .\server\data\fixtures\test-role.json

# 从 tools/analyze_game_tcp_pcap.py 生成的重组 JSON 创建 fixture
python -m server.fixture_tool from-capture .\server\data\captures\game-frames.json .\server\data\fixtures\captured-role.json --sdk-user-id 1 --login-open-id 1
```

fixture 只应来自获准的本地游戏 TCP 被动捕获；不要将 SDK 支付回调流量或热更新流量导入此目录。

配置文件按以下优先级生效：显式命令行参数 > TOML 配置 > 环境变量 > 内置默认值。默认配置文件缺失时仍使用内置默认值；显式指定但不存在或格式错误的配置文件会阻止启动。

可通过命令行指定配置文件：

```powershell
python -m server.main --config .\server\config.toml
python -m server.game_tcp --config .\server\config.toml
```

游戏 TCP 和 SDK 参数现在集中在 `server/config.toml`：

```toml
[http]
host = "0.0.0.0"
port = 8080

[sdk]
local_base_url = "http://192.168.1.100:8080"
domain_urls = ["http://192.168.1.100:8080"]
auto_credit_g_points = true

[game]
tcp_host = "0.0.0.0"
tcp_port = 21001
advertise_host = "192.168.1.100"
server_id = 4
fixture_dir = "server/data/fixtures"
```

旧环境变量仍可用于未在 TOML 中填写的字段：

```powershell
$env:GAME_TCP_HOST = "0.0.0.0"
$env:GAME_TCP_PORT = "21001"
$env:GAME_TCP_ADVERTISE_HOST = "192.168.1.100"
$env:GAME_SERVER_ID = "4"
$env:GAME_FIXTURE_DIR = ".\server\data\fixtures"
```

`system/info` 的 URL 字段可通过环境变量覆盖：

```powershell
$env:SDK_LOCAL_BASE_URL = "http://192.168.1.100:8080/"
$env:SDK_DOMAIN_URLS = "http://192.168.1.100:8080"
$env:SDK_SITE_URL = "http://192.168.1.100:8080/"
$env:SDK_PAY_URL = "http://192.168.1.100:8080/"
$env:SDK_GAME_TRACK_URL = "http://192.168.1.100:8080/api/sdk/system/gameTrack"
$env:SDK_UPLOAD_IMAGE_URL = "http://192.168.1.100:8080/api/sdk/upload"
$env:SDK_MEDIA_URL = "http://192.168.1.100:8080/"
$env:SDK_AUTO_CREDIT_G_POINTS = "1"
$env:GAME_RESOURCE_URL = "/ReleaseGame18/Android/1.2.5"
$env:GAME_RESOURCE_ENV_TYPE = "prod"
$env:GAME_TCP_TRACE = "0"
```

`GAME_TCP_TRACE=1` 或启动参数 `--trace` 会记录游戏 TCP 收发方向、消息号、序号、flag、body 长度和摘要，不记录完整 token。登录日志还会记录 `OpenId/UserId`、fixture 匹配键、token 指纹和拒绝原因。

配置文件中的 `sdk.auto_credit_g_points` 控制已确认商品在 G 点不足时是否自动补充差额，默认启用。旧环境变量 `SDK_AUTO_CREDIT_G_POINTS` 仅在 TOML 未填写该字段时生效。自动补充和商品扣款在同一个 SQLite 事务中完成，重复订单不会重复补充或发放。

`/resource/url` 默认返回与原版抓包一致的 `/ReleaseGame18/Android/1.2.5` 和 `prod`。如需切换到完整 CDN URL 或本地资源镜像，修改配置文件中的 `game.resource_url`；旧环境变量 `GAME_RESOURCE_URL` 仅在 TOML 未填写时生效。接口只返回资源配置，不下载 Manifest、Bundle 或其他资源，也不请求原始支付回调域名。

服务端会将关键 SDK 结果同时写入 `server/data/server.log` 和当前控制台。`system/gameTrack` 日志会区分请求格式错误、缺失/无效 Token 和成功入库；支付日志会记录商品、结算状态和扣款后余额。为避免泄露凭据，只记录 Token 指纹，不记录完整 Token 或轨迹内容。注意 Uvicorn 的 HTTP `200` 只代表传输完成，仍需查看加密响应中的 `status` 和 `errorCode`。

## Python 客户端与测试

加密登录冒烟测试：

```powershell
python -m server.client
```

该客户端会登录默认账号，发送一条加密的 `system/gameTrack` 冒烟请求，并调用 `spend/create2` 验证本地支付响应和订单记账。默认使用未知金额 `1`，不会访问请求中的原始 `notifyUrl`。

自动补充默认启用，实机购买已确认商品时不需要预先充值 G 点。若要按真实余额流程测试，可显式关闭自动补充：

```powershell
$env:SDK_AUTO_CREDIT_G_POINTS = "0"
```

也可以先显式给本地测试账号充值 G 点，再手动启动服务端：

```powershell
python -m server.client --credit-g-points 24900
```

六档商品价格总和为 `24900` G 点。也可以使用 `--purchase-amount 60` 做单档测试。该充值命令直接操作本地 SQLite，不提供远程管理员接口。

完整测试：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server tests
```

## 常见故障

### `ModuleNotFoundError: No module named 'server'`

命令必须在包含 `server` 文件夹的工程根目录执行。可以先确认：

```powershell
Test-Path .\server\main.py
```

### 8080 端口被占用

查看监听进程：

```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen
```

确认是本服务后停止对应 PID，或临时使用其他端口进行测试。

### AES 依赖缺失

依赖必须安装到工作目录：

```powershell
python -m pip install `
  --target .tools/server_deps `
  --cache-dir .cache/pip `
  pycryptodome
```

### 无效 Token

确认请求外层的 `token` 使用登录响应中的 Token。服务端会返回 `errorCode=2002`，不会把无效 Token 当作匿名登录。

## 当前边界

热更新域名 `pxcdn.jhdwxp.com` 保持原始服务器不变。只有在 SDK 服务端协议测试完成，并确认完整热更新路径后，才考虑修改 APK 的 SDK 域名配置。
