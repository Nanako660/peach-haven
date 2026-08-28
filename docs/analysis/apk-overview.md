# APK 与 Unity 运行时分析

> **分类**：技术分析 / 引擎与资源  
> **状态**：已确认 (Confirmed by static analysis)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

## 基本信息

| 项目 | 结果 |
| --- | --- |
| 原始文件 | `桃.apk` |
| 包名 | `com.IdolTime.Cards.game18` |
| 引擎形态 | Unity IL2CPP |
| Android 明文 HTTP | Manifest 中 `android:usesCleartextTraffic="true"` |
| 主要资源系统 | YooAsset `DefaultPackage` |
| 热更新线索 | `HotUpdate.dll`、HybridCLR |

包名和明文 HTTP 配置来自 `decoded/AndroidManifest.xml`。程序集名称来自 `decoded/assets/bin/Data/ScriptingAssemblies.json`。

## 运行时程序集

程序集清单中可以确认以下关键组件：

- `YooAsset.dll`
- `YooAsset.Custom.dll`
- `HybridCLR.Runtime.dll`
- `HotUpdate.dll`
- `Dynamic.SDK.dll`
- `IdolTime.SDK.dll`
- `IdolTime.Encrypt.dll`

这说明 APK 不是只有静态内置场景，启动和游戏逻辑可能依赖运行时程序集、YooAsset 资源和热更新代码的组合。

## IL2CPP 文件

主要 IL2CPP 输入位于 `files/il2cpp`：

- `files/il2cpp/Metadata/global-metadata.dat`
- `files/il2cpp/Resources/`
- `files/il2cpp/unity.ver`

`global-metadata.dat` 是后续类型、字符串和方法关联分析的重要输入。本目录中的 IL2CPP 文件来自 APK 运行数据提取，不应直接覆盖。

## YooAsset 资源

静态资源位于：

- `decoded/assets/yoo/DefaultPackage/`
- `decoded/assets/yoo/DefaultPackage/PackageManifest_DefaultPackage_1.2.3.bytes`

运行时缓存位于：

- `files/yoo/DefaultPackage/`
- `files/yoo/DefaultPackage/CacheBundleFiles/`
- `files/yoo/DefaultPackage/ManifestFiles/`
- `files/yoo/DefaultPackage/ApplicationFootPrint.bytes`

静态 APK 内的 `PackageManifest_DefaultPackage_1.2.3.bytes` 与设备缓存中的 Manifest/Bundle 文件应分开记录。静态资源只能说明 APK 内置内容，不能单独证明线上热更新路径或当前线上版本。

## 分析工具与派生目录

- `apktool.jar`：APK 解包
- `decoded`：APKTool 解包输出
- `decoded_smali_20260822`：smali 分析输出
- `.tools/unitypy`：Unity 资源读取和提取
- `files.zip`：运行数据归档

工具和缓存必须留在工作目录，详见根目录 [`AGENTS.md`](../../AGENTS.md)。

## 结论分类

### 已确认

- APK 包名为 `com.IdolTime.Cards.game18`。
- Manifest 允许明文 HTTP。
- 程序集清单包含 YooAsset、HybridCLR 和 `HotUpdate.dll`。
- APK 和运行缓存均存在 YooAsset `DefaultPackage` 资源。

### 推断

- 热更新后的逻辑可能由 `HotUpdate.dll` 和 YooAsset 资源共同加载。
- 只替换 SDK API 地址不一定能解决热更新逻辑访问原服务端的问题。

### 待验证

- 当前设备最终加载的热更新版本。
- `pxcdn.jhdwxp.com` 的完整资源根路径。
- 热更新代码是否调用未实现的 SDK 业务接口。

