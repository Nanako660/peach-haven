# SDK 网络协议分析

> **分类**：技术分析 / 协议加解密  
> **状态**：已确认 (Confirmed by static analysis)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 证据来源

主要来源：

- `decoded_smali_20260822/smali/com/charles/weblib/network/api/ApiService.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/network/interceptor/AESUtils.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/network/interceptor/AesInterceptor.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/network/result/ApiResult.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/model/GameSystemData.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/model/UserData.smali`

## AES 传输层

APK 的 OkHttp `AesInterceptor` 会把 Retrofit 生成的普通 JSON 包装为外层 Envelope，然后加密整个 JSON。请求不是普通 JSON 文本。

- 算法：AES-128 ECB
- Java transformation：`AES/ECB/PKCS5Padding`
- Python 对应：PKCS7 padding，块大小 16 字节
- 密钥：`f237311e06398eac`
- 请求媒体类型：`application/octet-stream`
- 响应：同样是 AES 密文；APK 解密后按 JSON/API Result 解析

请求解密后的结构：

```json
{
  "token": "opaque-token",
  "deviceId": "device-id",
  "data": {
    "username": "test",
    "password": "test1234",
    "channel_code": "local"
  }
}
```

`AesInterceptor` 还会从本地 KVStore 读取 `token`、`deviceId` 和 `gameKey`。如果本地存在 `gameKey` 且请求数据没有 `game_key`，拦截器会补入 `game_key`。

## ApiResult

响应明文结构：

```json
{
  "status": "y",
  "time": "unix_timestamp",
  "errorCode": "",
  "error": "",
  "data": {}
}
```

`ApiResult.smali` 确认字段为 `status`、`time`、`errorCode`、`error` 和 `data`。成功状态为 `status="y"`。本地兼容服务端对无效或过期 Token 返回 `status="n"`、`errorCode="2002"`。

## APK 中恢复出的完整 SDK API

以下路径来自 `ApiService.smali`。它们是静态分析结果，不代表全部已经在 Python 服务端实现。

| 路径 | 当前状态 |
| --- | --- |
| `/api/sdk/User/bindEmail` | 已分析，未实现 |
| `/api/sdk/User/password` | 已分析，未实现 |
| `/api/sdk/user/validateToken` | 已实现 |
| `/api/sdk/User/vipReceiveCoin` | 已分析，未实现 |
| `/api/sdk/Recharge/createAndSpend` | 已实现本地模拟成功响应 |
| `/api/sdk/Recharge/create` | 已实现本地模拟成功响应 |
| `/api/sdk/spend/create2` | 已实现本地模拟成功响应 |
| `/api/sdk/user/kf` | 已分析，未实现 |
| `/api/sdk/Help/lists` | 已分析，未实现 |
| `/api/sdk/game/more` | 已分析，未实现 |
| `/api/sdk/Recharge/history` | 已分析，未实现 |
| `/api/sdk/UserProduct/getProductList` | 已实现空商品列表兼容响应 |
| `/api/sdk/system/info` | 已实现 |
| `/api/sdk/TransactionLog/lists` | 已分析，未实现 |
| `/api/sdk/user/vipLists` | 已分析，未实现 |
| `/api/sdk/Login/account` | 已实现 |
| `/api/sdk/Login/quickAccount` | 已实现 |
| `/api/sdk/Login/username` | 已实现 |
| `/api/sdk/Login/upPass` | 已分析，未实现 |
| `/api/sdk/Mail/sendVerificationCode` | 已分析，未实现 |
| `/api/sdk/login/singleGameVerify` | 已实现 |
| `/api/sdk/User/doUpdate` | 已实现 |
| `/api/sdk/system/gameTrack` | 已实现最小兼容处理 |

另外，本地服务端增加未加密的 `GET /healthz`，它不是 APK SDK 接口。

## 当前实现的业务规则

### 登录

- `/api/sdk/Login/account` 使用 `username`、`password` 和可选 `channel_code` 登录。
- 成功后签发随机不透明 Token。
- 默认账号为 `test / test1234`。
- 密码使用 PBKDF2-HMAC-SHA256 哈希，不保存明文密码。

### 注册和快捷账号

- `/api/sdk/Login/username` 创建新账号并立即签发 Token。
- `/api/sdk/Login/quickAccount` 生成随机用户名和密码，返回 `QuickAccountData` 形状的对象。

### Token

- `/api/sdk/user/validateToken` 成功返回 `data=true`。
- Token 保存创建时间、过期时间、设备 ID和用户关联。
- APK 的 `UserSessionManager` 会将登录响应中的 Token 保存为 `原始Token_用户ID`，后续 AES 外层请求会发送这个复合值；本地服务端会拆分并同时校验原始 Token 和用户 ID 后缀。
- 无效 Token 返回 `errorCode=2002`。

### 资料更新

`/api/sdk/User/doUpdate` 支持持久化 `nickname`、`sex`、`headico` 等资料。请求的 `type` 字段保留用于兼容 APK，但服务端按字段白名单更新资料。

### 系统信息

`/api/sdk/system/info` 返回 `GameSystemData` 最小结构：

- `site_url`
- `pay_url`
- `game_track_url`
- `upload_image_url`
- `media_url`
- `user`
- `task_points`

URL 默认指向局域网服务，也可以通过环境变量覆盖。

### 本地支付模拟

以下接口在本地服务中要求有效外层 Token，并使用标准 AES API 响应返回成功：

- `UserProduct/getProductList` 返回 `is_new`、`product_list` 和 `pay_banner` 三个空数组。
- `Recharge/create` 返回 `success=true`、`msg=success` 和空 `url`。
- `Recharge/createAndSpend` 返回空 `url`。
- `spend/create2` 记录加密请求中的订单字段；对已确认的六档实机金额按 G 点价格扣款，并记录商品基础数量和首购双倍奖励，再返回空 `extra`，对应 APK `GameCreateItemModel`，使 SDK 进入支付成功回调。未知金额仍只记账；服务端不访问 `notifyUrl`，也不修改 APK 内部库存。

这些接口仅用于本地兼容测试，不连接真实支付平台。G 点余额和商品发放分别保存在本地账本；`notifyUrl` 仅作为订单字段保存，不会被服务端访问。字段形状来自 `ApiService.smali`、支付模型以及 `GameSdkPay` 的运行分支；游戏客户端是否消费 `product_grants` 仍需单独验证。

客户端支付成功与游戏内商品到账的详细分析见 [`client-payment-chain-analysis.md`](client-payment-chain-analysis.md)。该记录确认了 SDK `PayCallBack`、G 点 `NotifyBalance` 与游戏服 `SCRoleBaseInfoNtf`、`SCItemChangeNtf`、`SCGiftBuyNtf` 之间的边界。

### 单机验证

`/api/sdk/login/singleGameVerify` 兼容 APK 登录前调用：

- 如果外层 Token 有效，直接返回用户资料。
- 如果没有有效 Token，则用 `data.username` 和 `data.password` 验证账号，签发 Token 并返回用户资料。
- 第一阶段对有效用户默认返回已购买/可进入游戏状态。

## UserData 兼容字段

服务端返回的最小用户结构包含：

- `token`
- `userId`
- `user_id`（与 `userId` 同值，兼容 APK 的 Gson `SerializedName`）
- `account`
- `username`
- `nickname`
- `headico`
- `sex`
- `email`
- `has_login`
- `balance`
- `point`
- `is_vip`
- `preference_value`
- `return_product`
- 下载/VIP/分组等默认字段

字段命名遵循 Gson `SerializedName`，例如 `headico`、`is_vip`、`nickname_changed_30` 和 `preference_value`。

## 验证结果

已通过：

- AES 固定向量和加解密往返测试
- Python 加密客户端登录
- 注册、登录、Token 校验、资料更新
- `system/info` 和 `singleGameVerify`
- 本地支付兼容接口的成功响应和无效 Token `errorCode=2002`
- 重启服务后账号和 Token 持久化
- 无效 Token `errorCode=2002`
