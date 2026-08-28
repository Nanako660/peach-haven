# 热更新与 YooAsset 分析

> **分类**：技术分析 / 资源更新与 CDN  
> **状态**：已确认 (Confirmed by packet capture & static analysis)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 抓包结论

已从运行时抓包得到热更新/CDN 域名：

```text
pxcdn.jhdwxp.com
```

当前只确认 Host，尚未确认完整资源根路径。完整路径必须通过继续抓包记录：

- 完整 URL 和路径
- HTTP 方法
- 请求参数和查询字符串
- 请求/响应头
- 响应状态码
- `Content-Type`
- 是否返回 Manifest、版本号、Bundle 或哈希文件
- 请求发生时的本地包版本和热更新版本

## 静态分析结果

静态资源位置：

- `decoded/assets/yoo/DefaultPackage/`
- `decoded/assets/yoo/DefaultPackage/PackageManifest_DefaultPackage_1.2.3.bytes`

运行数据位置：

- `files/yoo/DefaultPackage/ManifestFiles/`
- `files/yoo/DefaultPackage/CacheBundleFiles/`
- `files/yoo/DefaultPackage/ApplicationFootPrint.bytes`

程序集清单中存在：

- `YooAsset.dll`
- `YooAsset.Custom.dll`
- `HotUpdate.dll`
- `HybridCLR.Runtime.dll`

## 域名未出现在静态文本中的含义

当前对 `decoded` 和 `decoded_smali_20260822` 的文本搜索未找到 `pxcdn.jhdwxp.com` 明文。

这只能说明域名没有以普通明文出现在当前搜索范围，不能证明它不存在于：

- 二进制资源
- 加密配置
- 远程配置
- 运行时拼接结果
- 设备缓存或网络响应

因此，当前将其标记为“抓包确认、静态路径待验证”。

## SDK 与热更新的边界

SDK API 使用 `AesInterceptor` 加密 JSON，请求路径是 `/api/sdk/...`。YooAsset/HotUpdate 资源请求通常是 Manifest、版本和 Bundle 文件，两者不是同一套协议。

当前策略：

- SDK 登录接口可以先重定向到局域网 Python 服务端。
- `pxcdn.jhdwxp.com` 和完整热更新路径继续使用原始服务器。
- 不把热更新域名指向 `192.168.x.x:8080`。

## 本地镜像前置条件

如果后续需要本地镜像热更新，必须先确认：

1. Manifest 文件命名和路径。
2. 版本号或资源版本选择规则。
3. Bundle 哈希、大小和校验方式。
4. 请求是否需要特定 Header、Query 或平台参数。
5. APK 是先请求远端 Manifest，还是先读取本地缓存。
6. 热更新代码是否会在加载后访问额外业务 API。

未完成上述确认前，不应修改热更新地址。

