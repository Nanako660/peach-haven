# 客户端支付链路与商品发放分析记录

> **分类**：技术分析 / 计费与状态机  
> **状态**：已确认 (Confirmed by static analysis & runtime capture)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 记录范围

本记录整理截至 **2026-08-22** 的客户端静态分析、模拟器运行日志和本地 SQLite 数据库结果。模拟器日志本身显示为 **2026-08-23**，比当前系统日期提前一天，因此日志时间用于判断相对顺序，不用于校准实际日期。

本阶段遵守以下边界：

- 不修改 `桃.apk`。
- 不修改 YooAsset、HotUpdate 或 `pxcdn.jhdwxp.com` 地址。
- 不访问原始支付回调域名。
- 服务端只作为本地 SDK 兼容服务，不主动向原始 `notifyUrl` 发起请求。

## 证据标记

- **Confirmed by static analysis（静态分析确认）**：由反编译 C#、smali、Protobuf 定义或枚举直接确认。
- **Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**：由模拟器日志、服务端日志或数据库记录直接确认。
- **Inferred and still requiring validation（推断，仍需验证）**：根据代码结构、命名或缺失链路推断，尚未通过原始服务端或完整游戏服抓包验证。

## 一、完整支付流程

### 1. 游戏获取订单号

**Confirmed by static analysis（静态分析确认）**

客户端购买入口首先构造 `CSOrderNoReq`，通过游戏长连接协议发送消息号 `377`，等待 `SCOrderNoAck`。请求包含：

- `Platform`
- `ServerId`
- `ShopId`
- `GoodsId`
- `Quantity`
- `OwnerKey`

对应代码位于：

```text
.tools/client_decompiled/View.dll/IdolGame/SDKComponentSystem.cs:316
.tools/client_decompiled/View.dll/IdolGame/SDKComponentSystem.cs:326
```

`SCOrderNoAck` 提供订单号、回调地址、商品、数量和订单价格。客户端随后构造 `PayData`，关键字段为：

```text
orderNo       = message.OrderNo
productId     = shopConfig.Id
price         = message.OrderPrice
amount        = 1
payNotifyUrl  = message.NotifyUrl
```

对应代码位于：

```text
.tools/client_decompiled/View.dll/IdolGame/SDKComponentSystem.cs:515-532
```

### 2. SDK 调用 `spend/create2`

**Confirmed by static analysis（静态分析确认）**

Android SDK 的 `EighteenGameSDK.UnityPay` 从 `PayData` 中读取：

- `price`
- `orderNo`
- `payNotifyUrl`
- `extra`

随后调用 `GameSdkManager.sendPayUrl`。Retrofit 接口将请求发送到：

```text
POST /api/sdk/spend/create2
```

对应证据：

```text
decoded_smali_20260822/smali/com/idoltimex/lib18game/EighteenGameSDK.smali:875-967
decoded_smali_20260822/smali/com/charles/weblib/network/api/ApiService.smali:226-248
```

客户端支付请求中的 `notifyUrl` 是请求字段的一部分。当前静态代码中没有发现 SDK 在收到 `spend/create2` 成功响应后直接访问该 URL 的逻辑。

### 3. SDK 成功回调

**Confirmed by static analysis（静态分析确认）**

只要 `/api/sdk/spend/create2` 返回成功的 `NetworkResult.Success`，SDK 就调用 `createPaySuccess`。`GameCreateItemModel` 只有一个 `extra` 字段，客户端没有根据 `extra` 解析钻石数量或背包物品。

`EighteenGameSDK$6.createPaySuccess` 的行为是：

1. 设置 `callPay=true`。
2. 输出 `支付成功：extra = ...`。
3. 调用 `PayCallBack("")`。

Unity 侧收到回调后：

1. 发布 `SDKPayCallback(true)`。
2. `UIChargePopPagePayCallback` 仅设置 `sdkPay=true`。
3. 延迟关闭支付窗口。

对应证据：

```text
decoded_smali_20260822/smali/com/idoltimex/lib18game/EighteenGameSDK$6.smali:76-110
.tools/client_decompiled/View.dll/IdolGame/SDKCallback.cs:146
.tools/client_decompiled/View.dll/IdolGame/UIChargePopPagePayCallback.cs:74
```

因此，`PayCallBack` 只能证明 SDK 订单创建接口返回成功，不能证明游戏内商品已经到账。

### 4. G 点刷新

**Confirmed by static analysis（静态分析确认）**

支付窗口失去焦点或重新获得焦点时，Android SDK 读取 SDK 账户余额并通过：

```text
NotifyBalance
```

发送给 Unity。Unity 将其保存为 `SDKComponent.GPointBalance`。该余额属于 SDK 账户的 G 点，不是游戏角色的钻石。

对应证据：

```text
decoded_smali_20260822/smali/com/idoltimex/lib18game/EighteenGameSDK.smali:46-82
.tools/client_decompiled/View.dll/IdolGame/SDKComponentSystem.cs:840-858
```

## 二、实机运行证据

### 1. SDK 回调日志

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**

使用项目内 `.tools/adb/adb.exe` 读取模拟器 logcat，得到两次完整的 SDK 支付成功序列：

```text
08-23 02:28:26.984  D SdkVirtualClass: UnityPay:extra:{"orderNo":"15059138341507072","serverName":"桃花烂漫","userName":"<TEST_PLAYER>","serverId":"4","userId":"<TEST_USER_ID>"}
08-23 02:28:27.708  D GameLogger: AesInterceptor POST http://192.168.1.100:8080/api/sdk/spend/create2
08-23 02:28:27.742  D SdkVirtualClass: 支付成功：extra =
08-23 02:28:27.742  D SdkVirtualClass: ..."function":"PayCallBack","data":"","extData":""
08-23 02:28:27.776  D SdkVirtualClass: ..."function":"NotifyBalance","data":"0","extData":""
```

第二笔订单：

```text
08-23 02:28:43.902  D SdkVirtualClass: UnityPay:extra:{"orderNo":"15059140641689600","serverName":"桃花烂漫","userName":"<TEST_PLAYER>","serverId":"4","userId":"<TEST_USER_ID>"}
08-23 02:28:44.586  D GameLogger: AesInterceptor POST http://192.168.1.100:8080/api/sdk/spend/create2
08-23 02:28:44.621  D SdkVirtualClass: 支付成功：extra =
08-23 02:28:44.621  D SdkVirtualClass: ..."function":"PayCallBack","data":"","extData":""
08-23 02:28:44.653  D SdkVirtualClass: ..."function":"NotifyBalance","data":"0","extData":""
```

这证明：

- APK 确实访问了本地 `spend/create2`。
- 本地接口响应被 SDK 判定为成功。
- `PayCallBack` 已发送到 Unity。
- G 点余额刷新结果为 `0`。

当前日志中没有出现明确的 `SCGiftBuyNtf`、`SCItemChangeNtf` 或 `SCRoleBaseInfoNtf` 文本日志。由于游戏长连接消息是二进制 Protobuf，日志中没有名称并不能单独证明消息绝对没有到达；但与客户端静态调用链结合后，可以确认没有看到商品到账结果。

### 2. 服务端日志

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**

本地服务端日志确认两笔真实订单已被 SDK 接收：

```text
payment order recorded endpoint=spend/create2 order_id=41
user_id=1 order_num=15059138341507072 amount=60
product_id=4000001 settlement=granted balance_after=0

payment order recorded endpoint=spend/create2 order_id=42
user_id=1 order_num=15059140641689600 amount=300
product_id=4000002 settlement=granted balance_after=0
```

本地服务端没有访问原始 `notifyUrl`，也没有接管 `pxcdn.jhdwxp.com`。

### 3. SQLite 记录

**Confirmed by packet capture or runtime observation（抓包或运行时观察确认）**

数据库文件：

```text
server/data/server.sqlite3
```

订单记录：

| 订单 ID | orderNum | 金额 | 商品 | 状态 |
| ---: | --- | ---: | --- | --- |
| 41 | `15059138341507072` | 60 | `4000001` | `completed` |
| 42 | `15059140641689600` | 300 | `4000002` | `completed` |

商品账本记录：

| payment_order_id | product_id | 基础数量 | 首购奖励 | 总数量 | 首购标记 |
| ---: | --- | ---: | ---: | ---: | ---: |
| 41 | `4000001` | 20 | 0 | 20 | 0 |
| 42 | `4000002` | 110 | 110 | 220 | 1 |

G 点流水显示，本地服务端先自动补充对应 G 点，再立即扣除：

```text
订单 41：auto_credit +60，spend -60，余额 0
订单 42：auto_credit +300，spend -300，余额 0
```

这表示本地账本已经完成测试记账，但 `product_grants` 不是 APK 或游戏服读取的数据源，不能直接改变游戏角色状态。

## 三、客户端实际发放入口

### 1. 游戏钻石

**Confirmed by static analysis（静态分析确认）**

游戏角色钻石保存在 `RoleBase.Diamond`，不是 SDK 的 G 点余额，也不是普通的本地支付账本字段。

客户端使用 `SCRoleBaseInfoNtf` 更新角色基础数据。该消息包含 `Diamond` 字段，消息号为 `76`；处理器最终执行：

```csharp
userInfo.RoleBase = message.RoleBase;
```

对应证据：

```text
.tools/client_decompiled/Model.dll/Serverproto/SCRoleBaseInfoNtf.cs:22
.tools/client_decompiled/Model.dll/Serverproto/protoMsgId.cs:136
.tools/client_decompiled/Model.dll/IdolGame/SCRoleBaseInfoNtf_BattleRiskInfo_MsgHandler.cs:77
```

### 2. 背包物品

**Confirmed by static analysis（静态分析确认）**

`SCItemChangeNtf` 的消息号为 `121`。处理器调用：

```csharp
BagComponent.Instance.UpdateBagItem(message.Change);
```

该处理器只更新 `RoleBag.Items`，因此适用于普通道具、材料和礼包物品，不等同于直接修改角色钻石。

证据：

```text
.tools/client_decompiled/Model.dll/Serverproto/protoMsgId.cs:226
.tools/client_decompiled/Model.dll/IdolGame/ScItemChangeNtf_SetUserInfo_MsgHandler.cs:49
```

### 3. 礼包购买通知

**Confirmed by static analysis（静态分析确认）**

`SCGiftBuyNtf` 的消息号为 `237`，字段为：

- `Error`
- `Rewards`：`Map<int, int>`
- `OrderNo`

客户端处理成功消息时会：

1. 根据当前 `goodsId` 查找商店配置。
2. 发布 `ShopBuyItemServerSync`。
3. 显示 `Rewards` 中的奖励。
4. 发布购买完成事件。

对应证据：

```text
.tools/client_decompiled/Model.dll/Serverproto/SCGiftBuyNtf.cs:18-28
.tools/client_decompiled/Model.dll/Serverproto/protoMsgId.cs:408
.tools/client_decompiled/View.dll/IdolGame/ScGiftBuyNtf_MsgHandler.cs:87-122
```

该消息本身是游戏服到客户端的奖励通知，不是 SDK HTTP 接口的返回值。

## 四、订单回调协议判断

### `SSOrderCallBackReq`

**Confirmed by static analysis（静态分析确认）**

该 Protobuf 类型包含：

```text
Uid
OrderNo
Platform
ShopId
GoodsId
Quantity
OrderStatus
Sig
OwnerKey
TotalAmount
```

配套的 `SSOrderCallBackAck` 只包含 `Error` 和 `OrderNo`。

证据：

```text
.tools/client_decompiled/Model.dll/Serverproto/SSOrderCallBackReq.cs:16-52
.tools/client_decompiled/Model.dll/Serverproto/SSOrderCallBackAck.cs:16-20
```

在当前客户端反编译结果中：

- 未找到 `new SSOrderCallBackReq`。
- 未找到客户端发送该类型的调用点。
- `SSOrderCallBackReq` 没有对应的客户端 `protoMsgId` 枚举项。

### 方向判断

**Inferred and still requiring validation（推断，仍需验证）**

结合 `SS` 命名、字段结构以及缺少客户端发送点，`SSOrderCallBackReq` 很可能是 SDK/支付服务向游戏服务端提交订单结算的服务端协议，而不是 APK 主动调用的接口。

当前不能仅凭客户端程序集确认原始支付回调服务器是否按以下流程工作：

```text
spend/create2
    -> 原 SDK 服务端接收 notifyUrl
    -> 游戏服处理 SSOrderCallBackReq
    -> 游戏服发送 SCRoleBaseInfoNtf / SCItemChangeNtf / SCGiftBuyNtf
```

由于当前阶段不访问原始支付回调域名，该方向保留为待验证结论。

## 五、其他支付协议

### `CS_PAY_INFO_GET_REQ` / `CS_PAY_INFO_ORDER_OK_LIST_GET_REQ`

**Confirmed by static analysis（静态分析确认）**

客户端协议枚举中还存在：

- `CS_PAY_INFO_GET_REQ = 278`
- `SC_PAY_INFO_GET_ACK = 279`
- `SC_PAY_INFO_NTF = 280`
- `CS_PAY_INFO_ORDER_OK_LIST_GET_REQ = 281`
- `SC_PAY_INFO_ORDER_OK_LIST_GET_ACK = 282`
- `CS_RECHARGE_INFO_REQ = 283`
- `SC_RECHARGE_INFO_ACK = 284`

其中 `SCPayInfoOrderOKListGetAck` 包含 `RewardItemList`，说明协议设计上存在订单奖励列表或补偿查询的可能。

但在当前反编译的 `View.dll` 和 `Model.dll/IdolGame` 中没有找到这些请求的明确发送调用点，也没有找到对应的业务处理器。

### `SCPayForGoodsNtf`

**Inferred and still requiring validation（推断，仍需验证）**

`SCPayForGoodsNtf` 的字段包含 `ShopType`、`GoodsId`、`GoodsNum`、`ItemList` 和 `CpOrderId`，语义上像游戏服发放商品的通知。但当前没有发现对应的客户端消息枚举或处理器，因此不能把它作为当前 APK 的实际发放入口。

## 六、关键修正：`ItemID=4` 是角色钻石，不是背包项

### 1. 当前六档商品的实际状态字段

**Confirmed by static analysis（静态分析确认）**

商品配置把六档商品的奖励写成 `ItemID=4`，但 `ItemID=4` 的存储类型是角色资源。客户端 `BagComponentSystem` 对这类资源走特殊分支：

- `GetItemNum(4)` 直接返回 `RoleBase.Diamond`。
- `UseItem(4, num)` 直接扣减 `RoleBase.Diamond`。
- `UpdateBagItem` 只合并 `RoleBag.Items`，不会处理 `RoleBase.Diamond`。

对应证据：

```text
.tools/client_decompiled/Model.dll/IdolGame/BagComponentSystem.cs:56-96
.tools/client_decompiled/Model.dll/IdolGame/BagComponentSystem.cs:117-130
.tools/client_decompiled/Model.dll/IdolGame/BagComponentSystem.cs:193-210
.tools/client_decompiled/Model.dll/Serverproto/RoleBase.cs:32-38,150-170
```

因此，当前六档充值到账的主路径应是更新 `RoleBase.Diamond`，而不是发送只包含 `ItemData.ConfigId=4` 的 `SCItemChangeNtf`。后者只会更新背包 map，不能让主界面的钻石数量改变。

### 2. 在线推送必须带完整 `RoleBase`

**Confirmed by static analysis（静态分析确认）**

`SCRoleBaseInfoNtf(76)` 的处理器会先访问 `message.RoleBase.Exp`，随后把 `message.RoleBase` 整体替换到本地 `UserInfo`：

```text
.tools/client_decompiled/Model.dll/IdolGame/SCRoleBaseInfoNtf_BattleRiskInfo_MsgHandler.cs:56-78
```

这意味着本地游戏服不能只构造一个“仅含 Diamond 字段”的半截消息。可靠的实现应从角色账本读取当前完整 `RoleBase`，至少保留 `Uid`、`Exp`、`Coin`、`Diamond` 以及客户端当前使用的其他字段，再通过消息号 `76` 推送。`SCRoleBaseInfoNtf` 顶层的 `Diamond` 字段不能替代处理器实际使用的 `RoleBase` 字段。

`SCStartupInfoNtf(25)` 同样包含 `RoleBase` 和 `RoleBag`，客户端启动处理器会克隆合并这两个字段。因而实时推送解决的是“当前连接立即显示”，启动消息解决的是“重连后仍然存在”；两者都必须来自同一份持久化角色账本。

### 3. 游戏订单必须在 `377` 阶段建立映射

**Inferred and still requiring validation（推断，仍需验证）**

当前 SDK 的 `spend/create2` 请求中，与游戏商品和角色关联的信息实际可见为：

- `amount`
- `orderNum`
- `extra.orderNo`
- `extra.serverId`
- `extra.userId`

现有本地服务用金额反查六档商品，这只能覆盖已观察到的测试样本。正确的本地闭环应在处理 `CSOrderNoReq(377)` 时先保存待支付订单：

```text
orderNo -> gameUid / serverId / shopId / goodsId / quantity / orderPrice / notifyUrl
```

随后 `spend/create2` 以 `orderNum` 或 `extra.orderNo` 查找该记录，并校验角色、区服、金额和商品是否一致，再执行一次性结算。否则客户端可以拿一个合法金额替换另一个商品订单，服务端也无法可靠处理首购和重复订单。

## 七、支付查询协议与服务间证据

### 1. 客户端支付查询协议目前不是观察到的发放入口

**Confirmed by static analysis（静态分析确认）**

客户端消息枚举存在：

```text
CS_PAY_INFO_GET_REQ(278) / SC_PAY_INFO_GET_ACK(279)
SC_PAY_INFO_NTF(280)
CS_PAY_INFO_ORDER_OK_LIST_GET_REQ(281) / SC_PAY_INFO_ORDER_OK_LIST_GET_ACK(282)
CS_RECHARGE_INFO_REQ(283) / SC_RECHARGE_INFO_ACK(284)
SC_PAY_FOR_GOODS_NTF(305)
```

但当前 `View.dll`、`Model.dll/IdolGame` 中没有找到这些请求的发送调用、奖励领取处理器或 `SC_PAY_FOR_GOODS_NTF` 的客户端 handler。`SCPayInfoOrderOKListGetAck` 虽然包含 `RewardItemList`，目前只能说明协议设计支持订单奖励列表，不能说明客户端会在当前支付流程中主动拉取并发放。

证据：

```text
.tools/client_decompiled/Model.dll/Serverproto/protoMsgId.cs:456-506
.tools/client_decompiled/Model.dll/Serverproto/SCPayInfoOrderOKListGetAck.cs:16-24
```

因此，第一阶段不应把 `278/281/305` 当作已经确认的“补发按钮”。它们可以在本地游戏服基本登录链路稳定后作为兼容性补充测试。

### 2. `SS*` 类型更接近支付服务、游戏服和数据库之间的内部协议

**Confirmed by static analysis（静态分析确认）**

除客户端 `ApiReflection` 外，程序集还包含由 `GameReflection` 或 `DbReflection` 注册的支付内部类型：

- `SSPayInfoSaveReq` / `SSPayInfoSaveAck`：保存 `PayOrderSaveInfo`。
- `SSPayInfoOrderOKListGetReq` / `SSPayInfoOrderOkListGetAck`：读取已完成订单。
- `SSPayInfoOrderNtf`：推送一条支付订单信息。
- `SSOrderPaidDataSaveReq`：按 `Uid` 保存已支付的 `OrderData`。
- `SSOrderCallBackReq` / `SSOrderCallBackAck`：包含 `Uid`、`OrderNo`、`GoodsId`、`OrderStatus`、签名和金额。

`PayOrderSaveInfo` 又包含 `RewardList`、`SdkOrderId`、`OrderState` 等字段。这组类型与客户端消息枚举分离，支持“支付服务回调游戏服务，游戏服务保存订单并发放”的判断，但仍不能单凭客户端程序集确认原服务端的实际网络方向。

证据：

```text
.tools/client_decompiled/Model.dll/Serverproto/GameReflection.cs:387-389
.tools/client_decompiled/Model.dll/Serverproto/DbReflection.cs:301
.tools/client_decompiled/Model.dll/Serverproto/PayOrderSaveInfo.cs:18-92,222-240
.tools/client_decompiled/Model.dll/Serverproto/SSOrderCallBackReq.cs:16-52
```

### 3. 原游戏服路线

**Inferred and still requiring validation（推断，仍需验证）**

若继续使用原游戏服，完整路线应验证为：

```text
CSOrderNoReq(377)
  -> 游戏服/支付服务创建订单
  -> SDK spend/create2
  -> 支付服务按 notifyUrl 或内部协议回调游戏服
  -> 游戏服持久化订单和奖励
  -> 在线连接推送 76/121/237，离线用户在 25 启动数据中体现
```

当前阶段不访问原始回调域名，也不伪造 `SSOrderCallBackReq`。在获得原始回调抓包、服务端文档或可控测试环境前，这条路线只能作为待验证方案。

## 八、可执行的本地闭环方案

### 1. 目标架构

本地服务需要从“SDK HTTP 兼容层”扩展为两个协同组件：

```text
FastAPI SDK 层 :8080
  -> 记录 spend/create2
  -> 根据游戏订单号结算角色账本

游戏 TCP 层 :21001
  -> 处理 CS_LOGIN_REQ(3)
  -> 处理 CS_ORDER_NO_REQ(377)
  -> 发送启动数据和支付到账通知
```

两层共用 SQLite 中的订单和角色账本。`product_grants` 可以保留为审计记录，但不能继续作为唯一的“游戏库存”抽象。

### 2. 建议实施顺序

1. **先补订单登记，不改支付回调。** TCP 层处理 `377` 时生成唯一 `orderNo`，持久化 `serverId`、`gameUid`、`shopId`、`goodsId`、价格、数量和订单状态，再返回 `SCOrderNoAck`。
2. **再改结算校验。** `spend/create2` 解析 `extra`，按 `orderNum` 查待支付订单，校验 `userId/serverId/amount`；找不到映射或字段不一致时记录 `unresolved`，不发放。
3. **建立角色账本。** 最少需要 SDK 用户与游戏 `Uid` 的映射、`RoleBase` 持久化、钻石流水、每个商品的首购标记和订单幂等键。结算事务必须同时写订单状态、钻石增量和审计记录。
4. **实现在线到账。** 当前六档商品结算后，更新角色 `Diamond`，向当前 TCP 连接发送完整 `SCRoleBaseInfoNtf(76)`；可附带 `SCGiftBuyNtf(237)` 负责成功提示，但不能依赖它完成到账。
5. **实现重连到账。** `CS_LOGIN_REQ(3)` 成功后发送 `SCStartupInfoNtf(25)`，按实际启动顺序补齐 `SCStartupInfoEquipNtf(26)`、`SCStartupInfoHeroNtf(27)`、`SCStartupInfoEndNtf(28)` 等消息。至少要保证 `RoleBase` 中的钻石来自持久化账本。
6. **再扩展普通道具。** 只有未来确认商品奖励使用背包存储类型时，才通过 `SCItemChangeNtf(121)` 更新 `RoleBag.Items`；消息中的 `ItemData` 应使用角色当前 item key 和累计数量。

### 3. 必须先验证的最小用例

```text
登录 -> 获取订单号 -> 购买 60 档 -> 在线钻石增加 20
断线重连 -> 启动数据仍保留增加后的钻石
重复提交同一 orderNo -> 不重复增加
金额与 goodsId 不匹配 -> 不发放并记录 unresolved
```

通过上述用例后，再验证 300 档首购 `110 + 110`、非首购 `110`，最后才处理支付查询协议和其他商品类型。

## 九、根因结论

**Confirmed by static analysis and runtime observation（静态分析与运行时观察确认）**

当前链路的完成情况如下：

| 环节 | 状态 | 证据 |
| --- | --- | --- |
| SDK 登录 | 已完成 | 实机 HTTP 200 |
| Token 校验 | 已完成 | 实机 HTTP 200 |
| 获取游戏订单号 | 已完成 | `CSOrderNoReq` / `SCOrderNoAck` 代码链路 |
| `spend/create2` | 已完成 | 实机 HTTP 200、服务端订单 41/42 |
| SDK `PayCallBack` | 已完成 | logcat 明确记录 |
| G 点本地记账 | 已完成 | `wallet_transactions` |
| 游戏订单结算 | 未确认 | 当前未访问原始回调链 |
| 游戏钻石更新 | 未发生或未观察到 | 未见 `SCRoleBaseInfoNtf` 效果 |
| 背包/礼包发放 | 未发生或未观察到 | 未见 `SCItemChangeNtf` / `SCGiftBuyNtf` 效果 |

因此当前真实问题不是“支付接口没有成功”，而是：

```text
SDK 支付成功 != 游戏商品到账
```

本地服务端目前完成的是 SDK 订单接收、G 点测试记账和 SDK 成功回调；它没有把订单结算结果写入游戏服务器状态，也没有向当前游戏连接发送游戏协议奖励消息。

## 十、后续客户端侧验证计划

1. 在一次新购买前清理或记录 logcat 起点，完整保存 `CSOrderNoReq(377)` 和 `SCOrderNoAck(378)` 之后的长连接消息。
2. 重点观察消息号 `76`、`121`、`237` 是否在支付后出现，并按订单号关联。
3. 重新进入游戏后观察 `CS_PAY_INFO_GET_REQ(278)` 和 `CS_PAY_INFO_ORDER_OK_LIST_GET_REQ(281)` 是否实际发送；当前静态代码尚未找到调用点。
4. 比对游戏启动前后的 `RoleBase.Diamond` 和 `RoleBag.Items`，不要只看 SDK `NotifyBalance`。
5. 如果确认没有任何游戏服奖励消息，需要转为“游戏订单结算/游戏服协议兼容”任务；仅增加 SDK HTTP 路由或本地 `product_grants` 记录不足以完成发放。

## 当前边界

本记录不授权以下操作：

- 修改 APK 内支付回调逻辑。
- 向原始支付回调域名发送订单请求。
- 伪造或注入未经确认的游戏 Protobuf 奖励消息。
- 修改 YooAsset、HotUpdate 或原始 CDN 地址。
