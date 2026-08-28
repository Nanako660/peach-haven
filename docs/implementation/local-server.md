# Python 本地兼容服务端

> **分类**：系统实现 / Python 服务端  
> **状态**：已确认 (Confirmed by automated tests)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 目标

第一阶段只覆盖登录、Token 校验、用户资料、系统信息和进入游戏所需的最小 SDK 链路。服务端运行在局域网 `0.0.0.0:8080`，不修改 APK，不接管 YooAsset 热更新。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| `server/main.py` | FastAPI 应用、路由、请求解包和响应封包 |
| `server/storage.py` | SQLite 初始化、账号、PBKDF2 密码、Token 和资料 |
| `server/crypto.py` | AES 加解密、PKCS7 padding、协议 JSON |
| `server/client.py` | 标准库 Python 加密客户端冒烟测试 |
| `tests/test_server.py` | 协议、接口和持久化测试 |

## 运行

```powershell
python -m server.main
```

在包含 `server` 文件夹的工程根目录执行。可以先确认：

```powershell
Test-Path .\server\main.py
python -m server.main --config .\server\config.toml
```

## 路由

已实现：

- `GET /healthz`
- `POST /api/domain`：兼容普通 JSON/AES 的本地域名候选接口，不访问原始域名
- `POST /resource/url`：返回 `ResAPIService.SendHotfixAsync` 所需的热更新根地址，不主动访问原始 CDN
- `POST /api/sdk/Login/account`
- `POST /api/sdk/Login/username`
- `POST /api/sdk/Login/quickAccount`
- `POST /api/sdk/user/validateToken`
- `POST /api/sdk/User/doUpdate`
- `POST /api/sdk/system/info`
- `POST /api/sdk/system/gameTrack`
- `POST /api/sdk/UserProduct/getProductList`
- `POST /api/sdk/Recharge/create`
- `POST /api/sdk/Recharge/createAndSpend`
- `POST /api/sdk/spend/create2`
- `POST /api/sdk/login/singleGameVerify`

完整 SDK API 中其余接口仅完成静态分析，未实现邮件、VIP、账务、帮助列表和交易记录等业务。

`system/gameTrack` 首版只校验外层 Token，并将 `data` 原样保存到 SQLite 的 `game_tracks` 表；不解析轨迹字段，也不修改用户资料、余额、VIP、Token 或游戏资格。

本地支付接口不发起真实支付，也不访问原始 `notifyUrl`。`spend/create2` 会将支付请求记入 `payment_orders`，并对已确认的六档商品按 G 点价格扣款，将基础数量和首购双倍奖励记入 `product_grants`。G 点余额保存在 `wallet_accounts`，变更保存在 `wallet_transactions`。默认情况下，余额不足时会在同一事务中自动补充本次商品所需差额，再完成扣款和发放；自动补充流水类型为 `auto_credit`。设置 `SDK_AUTO_CREDIT_G_POINTS=0`、`false`、`no` 或 `off` 后恢复余额不足错误。未知金额仍只记账，不自动发放。

## 存储

SQLite 数据库：

```text
server/data/server.sqlite3
```

主要表：

- `users`
  - 用户名
  - PBKDF2 salt
  - PBKDF2-HMAC-SHA256 哈希
  - JSON 用户资料
  - 创建和更新时间
- `tokens`
  - 随机不透明 Token
  - 用户 ID
  - 设备 ID
  - 创建时间
  - 过期时间
- `game_tracks`
  - 用户 ID
  - 设备 ID
  - 原始轨迹 JSON
  - 接收时间
- `payment_orders`
  - 用户 ID、设备 ID和订单去重键
  - `orderNum`、`orderNo`、金额、类型、游戏键
  - 原始 `notifyUrl`
  - `extra` 原文和 JSON 解析结果
  - 原始支付 data JSON 和签名指纹
  - `unresolved`/`duplicate` 状态、请求次数和时间
- `wallet_accounts`
  - 用户当前 G 点余额
- `wallet_transactions`
  - G 点充值和商品扣款流水
- `product_grants`
  - 商品 ID、基础数量、首购奖励、总发放数量和订单关联

首次启动自动创建：

```text
用户名：test
密码：test1234
```

默认 Token 有效期为 30 天。过期 Token 在校验时清理并返回 `errorCode=2002`。

## 业务兼容点

- `Login/account`：登录并签发 Token。
- `Login/username`：保留 APK 注册入口，创建账号并签发 Token。
- `Login/quickAccount`：生成随机快捷账号，返回用户名和密码。
- `validateToken`：成功返回布尔值 `true`。
- `doUpdate`：按允许字段持久化资料。
- `system/info`：返回 `GameSystemData` 最小结构和当前 `UserData`。
- `system/gameTrack`：校验 Token 后记录原始轨迹并返回成功空对象。
- `UserProduct/getProductList`：返回空的新人商品、商品和支付 Banner 列表；实机商品映射来自 Unity 商品日志。
- `Recharge/create`：返回 `success=true`、`msg=success` 和空 `url`。
- `Recharge/createAndSpend`：返回带空 `url` 的成功对象。
- `spend/create2`：已确认金额按六档商品映射自动补充差额（默认开启）、扣除 G 点并写入 `product_grants`，再返回带空 `extra` 的成功对象，供 SDK 触发 `createPaySuccess`。关闭自动补充时余额不足返回 `errorCode=2003`；同一用户同一 `orderNum` 不会重复补充、扣款或发放。
- `singleGameVerify`：兼容已有 Token 和登录前用户名密码校验；第一阶段默认按已购买处理。

## 配置文件

默认配置文件是 `server/config.toml`，模板是 `server/config.toml.example`。配置优先级为：显式命令行参数 > TOML 配置 > 环境变量 > 内置默认值。

HTTP 和游戏 TCP 服务分别使用：

```powershell
python -m server.main
python -m server.game_tcp
```

`server/config.toml` 配置监听地址、SDK URL、游戏区服宣告地址、fixture、抓包文件、SQLite、Token 有效期、日志和支付开关。旧环境变量仍可用于 TOML 未填写的字段。

重要 URL 字段包括：

- `SDK_LOCAL_BASE_URL`
- `SDK_SITE_URL`
- `SDK_PAY_URL`
- `SDK_GAME_TRACK_URL`
- `SDK_UPLOAD_IMAGE_URL`
- `SDK_MEDIA_URL`
- `SDK_AUTO_CREDIT_G_POINTS`：已确认商品余额不足时自动补充差额，默认启用

`/resource/url` 支持以下环境变量：

- `GAME_RESOURCE_URL`：返回给客户端的热更新/CDN 根地址，默认 `/ReleaseGame18/Android/1.2.5`；该值可设置为完整 URL
- `GAME_RESOURCE_ENV_TYPE`：资源环境标识，默认 `prod`

这些 URL 只影响服务端返回的 `GameSystemData`，不会修改 APK 的热更新地址。`pxcdn.jhdwxp.com`、YooAsset 和 HotUpdate 地址保持原值。

`/resource/url` 默认响应与 2026-08-23 原版抓包一致：`env_type=prod`、`url=/ReleaseGame18/Android/1.2.5`。接口只返回配置，不下载 Manifest、Bundle 或其他资源，也不访问原始支付回调域名。

## 验证

```powershell
python -m unittest discover -s tests -v
python -m compileall -q server tests
python -m server.client
```

已经验证：AES 固定向量、加解密往返、注册、登录、Token 校验、资料更新、`system/info`、`system/gameTrack`、本地支付兼容接口、`spend/create2` 订单记账与幂等、非法 `extra` 原文保存、`singleGameVerify`、无效 Token、数据库重启持久化和局域网 `/healthz`。服务端不会根据 `notifyUrl` 发出外部回调请求。
