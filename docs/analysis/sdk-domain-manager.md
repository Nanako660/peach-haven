# SDK 域名管理机制

> **分类**：技术分析 / SDK 网络层  
> **状态**：已确认 (Confirmed by static analysis)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 证据来源

主要文件：

`decoded_smali_20260822/smali/com/charles/weblib/network/SdkDomainManager.smali`

调用方包括：

- `decoded_smali_20260822/smali/com/charles/weblib/network/NetworkClient.smali`
- `decoded_smali_20260822/smali/com/charles/weblib/storage/KVStore.smali`

## 内置 SDK 基地址

`SdkDomainManager` 初始化 `builtInReleaseBaseUrls`，顺序为：

1. `https://bjyinhegame.com`
2. `https://wangcaitt.com`
3. `https://shouyek.com`
4. `https://huochechushou.com`
5. `https://tywhtg.com`

列表第一个规范化后的地址会成为 `defaultReleaseBaseUrl`。

## `sdk_domains` 缓存

本地 KVStore 键为：

```text
sdk_domains
```

`loadCachedDomains()` 会读取 JSON 数组，逐项调用候选基地址规范化逻辑，过滤空值和无效值。域名更新逻辑会把规范化后的数组重新写回 `sdk_domains`。

## 规范化与回退

代码中存在以下行为：

- 去除或补齐基地址格式
- 规范化候选 URL
- 维护内置域名列表
- 暴露默认域名和完整候选域名列表
- NetworkClient 从 DomainManager 获取默认或候选基地址
- 网络失败时存在候选域名/备用域名尝试路径

因此，仅替换一个静态字符串不足以保证 SDK 永远访问局域网。后续 APK 接入需要同时处理：

1. `SdkDomainManager` 的内置基地址。
2. `sdk_domains` 本地缓存。
3. NetworkClient 的候选域名回退。
4. HTTP/HTTPS 和尾部斜杠规范化。

## 后续 APK 重定向方案

当前阶段不执行修改。协议测试完成后，计划使用局域网 HTTP 地址，例如：

```text
http://192.168.1.100:8080/
```

需要做到：

- 所有 SDK 备用域名都指向同一个局域网地址。
- 禁止 SDK 自动回退到原始域名。
- 清除 APK 的 `sdk_domains` 缓存。
- 不改变 YooAsset/HotUpdate 地址。

