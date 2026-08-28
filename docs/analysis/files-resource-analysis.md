# `files` 热更新资源分析

> **分类**：技术分析 / 资源与缓存  
> **状态**：已确认 (Confirmed by static analysis)  
> **免责声明**：本文档记录的内容仅供逆向工程、协议分析与学术研究交流，严禁用于任何商业用途。

分析日期：2026-08-22

## 范围

本报告只分析 `files/` 中的运行时数据、YooAsset 缓存和 IL2CPP 元数据，不修改 `桃.apk`、`files/` 原始输入或 YooAsset/HotUpdate 地址。

## 目录结论

### 已确认：静态目录结构

- `files/il2cpp/`：IL2CPP 元数据和托管资源流。
  - `Metadata/global-metadata.dat`：17,570,716 字节，IL2CPP metadata version 31。
  - `unity.ver`：`cf85713c-a192-4f77-98d2-65dd7dd1686e`。
  - `global-metadata.dat` 与 `decoded/assets/bin/Data/Managed/Metadata/global-metadata.dat` 的 SHA-256 完全一致。
- `files/yoo/DefaultPackage/`：YooAsset `DefaultPackage` 的运行时数据。
  - `ManifestFiles/`：两个 Manifest 版本 `1.2.3`、`1.2.5`，当前版本文件为 `1.2.5`。
  - `CacheBundleFiles/`：按文件哈希前两位分片的缓存 Bundle，每个 Bundle 目录包含 `__data` 和 `__info`。
  - `ApplicationFootPrint.bytes`：`0753517a6efe4b8e960fc9b5327fa2cb`。
- `files/why_you_care.dat`：包含 `LastLoginServerAddr`、`AccountKey`、`PasswordKey`、`Language` 和若干对话播放标记等本地状态键。其“Unity PlayerPrefs 类运行时状态文件”性质目前为推断，不属于 YooAsset 游戏资源。

证据：`files/` 目录清单、`files/il2cpp/unity.ver`、`files/il2cpp/Metadata/global-metadata.dat`、`files/yoo/DefaultPackage/ManifestFiles/`、`files/why_you_care.dat`。

## YooAsset Manifest

### 已确认：Manifest 格式与规模

通过 `files/yoo/DefaultPackage/ManifestFiles/PackageManifest_DefaultPackage_1.2.5.bytes` 和 Bundle 内抽出的 `YooAsset.dll` 静态反编译确认：

- Manifest 文件格式版本：`1.5.2`。
- Package：`DefaultPackage`。
- Package 版本：`1.2.5`。
- `EnableAddressable = true`。
- `LocationToLower = false`。
- `IncludeAssetGUID = false`。
- `OutputNameStyle = 1`。
- 逻辑资产：7,239 个。
- Bundle：3,414 个，全部为 `.bundle`，Manifest 记录的总文件大小为 1,898,688,102 字节。
- 资产记录包含地址、逻辑路径、GUID 字段、Bundle ID 和依赖 ID；Bundle 记录包含逻辑名、Unity CRC、文件哈希、文件 CRC、文件大小、加载方式和引用 ID。

证据：`YooAsset.DeserializeManifestOperation`、`YooAsset.BufferReader`、`YooAsset.PackageAsset`、`YooAsset.PackageBundle` 的反编译结果，以及上述 Manifest 二进制文件。

### 已确认：1.2.3 与 1.2.5

两个 Manifest 的逻辑资产路径和 Bundle 名称完全一致，只有 3 个 Bundle 记录发生变化：

- `assets_res_configs_gen.bundle`
- `assets_res_dll.bundle`
- `share_assets_res_rawdata_spine_front_10001.bundle`

当前 `ApplicationFootPrint.bytes` 与 `PackageManifest_DefaultPackage_1.2.5.hash` 同时存在，后者等于当前 `1.2.5` Manifest 的 MD5。

## 本地资源完整性

### 已确认：缓存 Bundle 完整

- `files/yoo/DefaultPackage/CacheBundleFiles/` 有 3,190 个 `__data`。
- 3,190 个 `__info` 全部可读取。
- 每个 `__info` 的 `dataFileCRC`、`dataFileSize` 与 `1.2.5` Manifest 的 `FileCRC`、`FileSize` 一致；实际 `__data` 文件大小也一致。
- 校验结果：3,190/3,190 通过，没有发现截断或缓存元数据不匹配。

### 已确认：APK 内置 Bundle 与缓存的合并结果

`decoded/assets/yoo/DefaultPackage/` 另有 58 个 APK 内置 Bundle。按文件哈希合并：

- Manifest 总 Bundle：3,414。
- `files` 缓存命中：3,190。
- APK 内置 Bundle 命中：58。
- 本地可用合计：3,248。
- Manifest 记录但当前本地快照不存在：166。

### 已确认：缺失项范围

166 个缺失 Bundle 全部属于 `assets_res_audio_lang_english_...`，共对应 166 个音频资产，Manifest 记录总大小约 247,929 字节。没有发现非英文语音、纹理、Prefab、配置或程序集 Bundle 缺失。

因此，`files` 是当前设备运行后形成的近全量资源快照，但不是 Manifest 的字节级全量镜像；缺口集中在未下载/未使用的英文语音资源。

## 资产组成

### 已确认：Manifest 逻辑资产分布

按 `Assets/Res/` 一级目录统计：

| 目录 | 数量 |
| --- | ---: |
| `Textures` | 2,795 |
| `Prefabs` | 2,487 |
| `Dialogue` | 897 |
| `Audio` | 506 |
| `Configs` | 448 |
| `Preset` | 63 |
| `DLL` | 40 |
| `DynamicSDK` | 1 |
| `ShaderVariant` | 1 |
| `Scenes` | 1 |

按扩展名统计，主要是 2,548 个 `.prefab`、2,435 个 `.png`、849 个 `.asset`、546 个 `.bytes`、362 个 `.jpg`、178 个 `.anim`、169 个 `.controller`、117 个 `.json`、25 个 `.mat`、8 个 `.shader`、1 个 `.shadervariants` 和 1 个 `.unity`。

## 配置与程序集

### 已确认：生成配置

从 `assets_res_configs_gen.bundle` 抽取出 116 个 JSON TextAsset：

- 113 个 `m_Dict` 表，共 239,336 条记录。
- 3 个 `m_Single` 配置，共 133 个字段：`tbconstconfig`、`tbglobalconfig`、`tbimgurl`。
- 四种本地化表各 18,586 条：`LocalizeConfig_CN/EN/JP/TW_Category.json`。
- 最大表为 `tbpaidtestnamekeyword.json`，130,911 条；其次是本地化表、`tbmonsterinfo`、`tbdialogue`、`tbherolevel` 等。
- 配置通过路径直接引用 Prefab、Texture、Scene 和 ShaderVariant，例如 `tbglobalconfig`/`tbconstconfig` 中包含战斗场景、点击特效、伤害数字、商店图标等资源路径。

分析抽取目录：`.tools/files_extracted/Assets/Res/Configs/Gen/`。

### 已确认：运行时程序集

`assets_res_dll.bundle` 包含 40 个 DLL/PDB 资产，核心程序集包括：

- `Base.dll`
- `Model.dll`
- `Model.Config.dll`
- `Model.Define.dll`
- `View.dll`
- `IdolTime.Model.dll`
- `IdolTime.UI.dll`
- `IdolTime.View.dll`
- `Dynamic.SDK.dll`
- `YooAsset.dll`
- `YooAsset.Custom.dll`
- `UniTask`、`Newtonsoft.Json`、`Google.Protobuf`、Spine、DOTween 和 Unity 模块程序集

`Assets/Res/DLL/` 中没有名为 `HotUpdate.dll` 的 TextAsset。另一方面，IL2CPP metadata 字符串表中确认存在 `HotUpdate.dll`、`Hot.Entrance`、`RunGame`、`HybridDllManager` 和 `LoadHotUpdate` 等名称。

证据：`files/il2cpp/Metadata/global-metadata.dat`、`assets_res_dll.bundle`、抽取的 `Base.dll` 与 `YooAsset.dll`。

## HotUpdate/HybridCLR 线索

### 已确认：静态代码线索

从 `Base.dll` 反编译可见 `Base.GameUpdate.HybridDllManager`，其流程名称包括：

- `LoadMetadataForAOTAssembly`
- `LoadHotUpdateAssemblies`
- `LoadHotUpdateDll`
- 入口类型名 `Hot.Entrance`
- 入口方法名 `RunGame`

从 `Base.GameUpdate.RemoteServices` 可确认 YooAsset 远端 URL 由“主 Host/备用 Host + 可选 Package 版本 + 文件名”组成。当前报告未修改这些地址。

### 推断：HotUpdate.dll 的本地缺失原因

当前 `files` 快照和 `1.2.5` Manifest 中没有直接的 `HotUpdate.dll` Bundle 资产，但 IL2CPP metadata 保留了 HotUpdate 类型和程序集名称。因此，HotUpdate 代码的实际字节来源仍需通过运行时加载日志、网络请求或 APK/启动流程进一步确认，不能仅凭当前 `files` 快照断定其已经被删除或未下载。

## 原始资源还原可行性

### 已确认：Bundle 文件可以字节级还原

当前快照中的 Bundle 不是加密后的不可读数据，而是完整的 UnityFS 文件：

- `CacheBundleFiles/<前两位>/<文件哈希>/__data` 的文件内容可直接作为 Bundle 使用；目录名与该文件的 MD5 一致。
- APK 内置的 58 个 Bundle 也以原始 Bundle 字节存在，文件名哈希与内容 MD5 一致。
- 按 `1.2.5` Manifest 合并后，本地可恢复 3,248/3,414 个逻辑 Bundle；缺失的 166 个全部是 English 语音 Bundle。
- UnityPy 1.25.3 已成功读取本地全部 3,248 个 Bundle，对应 3,249 个 SerializedFile、179,744 个 Unity 对象和 17,377 个容器路径，没有 Bundle 解析失败。

因此，可以恢复一套按 Manifest 逻辑 Bundle 名称命名的 `.bundle` 文件。此层是字节级恢复，不需要重新压缩或修改 Bundle 内容。

### 已确认：部分资源对象可以直接导出

本地导出探针位于 `.tools/restore_probe/`，已验证以下类型：

| 类型 | 还原结果 | 说明 |
| --- | --- | --- |
| `TextAsset`（`.bytes`、`.json`、DLL/PDB 等） | 原始内容级 | 可从 `m_Script` 按 `UTF-8 + surrogateescape` 写回；已验证 Spine `.skel.bytes`、RIFF/FEV 音频字节和 PE DLL 字节均可读出。 |
| `Texture2D`、`Sprite` | 像素级/视觉等价 | 可导出 PNG；原始 PNG/JPG 的压缩方式、元数据和源文件字节不会保留。 |
| `Mesh` | 几何数据级 | 可导出 OBJ；材质、骨骼、动画和 Unity 专有导入设置需要另行重建。 |
| `Shader` | 运行时着色器级 | 可导出可读文本或运行时数据，但不保证等于工程中的原始 Shader 源文件。 |
| `MonoBehaviour`、配置 `ScriptableObject` | 字段/类型树级 | 可导出 JSON 或原始序列化数据；依赖 DLL 中的类型定义。 |
| `GameObject`、Prefab | 运行时对象图级 | GameObject、Transform、Renderer、ParticleSystem 等对象和引用存在，可重建运行时 Prefab。 |
| Scene | 运行时场景数据级 | Scene 内的 GameObject、RenderSettings、LightmapSettings 等对象存在；不能直接恢复成原工程 YAML。 |
| `Material`、Animator、AnimationClip 等 | 对象数据级 | 可解析大部分字段，但 UnityPy 的通用导出器对部分 Unity 2022 对象需要定制导出。 |

### 推断：不能保证恢复原始 Unity 工程文件

Unity 打包前已经执行了导入和序列化。Bundle 中保留的是运行时对象，不一定包含以下原始工程信息：

- Prefab/Scene 的原始 YAML 排版、Prefab 修改记录、编辑器专用字段；
- PNG/JPG 的原始编码、EXIF 或导入前字节；
- Shader 的完整工程源代码和未编译变体；
- 资源的原始 `.meta` 文件、GUID 生成过程和 AssetImporter 设置。

所以“恢复原始资源文件”需要先定义目标：

1. **恢复游戏可加载资源**：可行。直接恢复 Bundle，或使用 UnityPy/Unity 编辑器导出对象即可。
2. **恢复资源内容**：大部分可行。文本、DLL、PDB、Spine 二进制和音频 `.bytes` 可按内容写回；纹理和网格可导出为常用格式。
3. **恢复开发者原始工程文件**：不能保证。Prefab、Scene、Material、Shader 等需要根据运行时对象重建，结果是功能等价物而不是字节级原件。

### 当前缺口

缺失的 166 个 Bundle 全部对应 English 语音资源。因此，非英文视觉资源、Prefab、Scene、配置和程序集已经具备恢复条件；若要求完整英文语音集，仍需单独补齐这 166 个 Bundle。该缺口不影响已经存在 Bundle 的还原，也不应与 SDK 登录流量混合处理。

证据：`files/yoo/DefaultPackage/CacheBundleFiles/`、`decoded/assets/yoo/DefaultPackage/`、`files/yoo/DefaultPackage/ManifestFiles/PackageManifest_DefaultPackage_1.2.5.bytes`、`.tools/restore_probe/`，以及本地 UnityPy 解析统计。

## 全量字节级恢复执行结果

### 已确认：本地快照已完成非破坏性恢复

恢复脚本：`.tools/restore_all_resources.py`。

输出目录：`.tools/restored_resources_1.2.5/`。

执行结果：

- 预期 Bundle：3,414 个。
- 已恢复 Bundle：3,248 个，字节总量 1,898,440,173 字节。
- 缺失 Bundle：166 个，全部为前述 English 语音资源；缺失哈希记录在 `index/missing_bundle_hashes.json`。
- Bundle 容器索引：17,377 条逻辑路径。
- 已恢复 TextAsset：1,063 个，字节总量 624,942,018 字节。
- TextAsset 路径冲突：0。
- 输出文件总数：4,318 个，约 2.53 GB（包含 Bundle、TextAsset 和索引文件）。

目录结构：

- `bundles/`：按 Bundle 内部 `AssetBundle.m_Name` 恢复的原始 `.bundle` 字节。
- `text_assets/`：按 Unity 容器路径恢复的 TextAsset 内容，包括 `.bytes`、`.json`、DLL/PDB 等。
- `index/bundles.json`：源文件、逻辑名称、来源、大小、MD5、SHA-256。
- `index/assets.json`：Bundle 内逻辑路径、Unity 类型、PathID 和所属 Bundle。
- `index/summary.json`：本次恢复统计。

### 已确认：恢复结果通过独立校验

第二轮校验确认：3,248 个输出 Bundle 全部存在，输出文件数量、大小和 MD5 均与恢复索引一致；本地 Bundle 哈希集合与 Manifest 哈希集合的差异正好是 166 个缺失项，没有额外或异常本地 Bundle。输入目录 `files/`、`decoded/`、APK 和既有逆向输出未修改。

## 内容级资源导出结果

### 已确认：运行时对象内容已完成全量导出

导出脚本：`.tools/export_resource_contents.py`。

输出目录：`.tools/restored_contents_1.2.5/`。

本次基于 3,248 个已恢复 Bundle 的 17,377 条 Unity 容器路径执行对象级导出，失败数为 0：

- `Texture2D`：2,740 个，导出 PNG 或序列化回退。
- `Sprite`：6,216 个，导出 PNG。
- `Mesh`：592 个，导出 OBJ，并保留网格字段元数据。
- `Shader`：172 个，129 个导出可读文本，43 个保留类型树 JSON 和序列化二进制回退。
- `GameObject`：2,633 个，导出包含组件、Transform、MonoBehaviour 和引用的运行时对象图 JSON。
- `MonoBehaviour`、`Material`、`AnimationClip`、`AnimatorController`、`RenderTexture`、`ShaderVariantCollection` 等：共 3,929 个，导出类型树 JSON。
- `Font`：6 个，导出 TTF/OTF 字节。
- `Scene`：26 个容器入口，导出场景对象清单；场景内容通过关联对象记录保留。
- `TextAsset`：1,063 个，引用前一阶段的字节保持输出，不重复改写。

覆盖校验：16,314 个非 TextAsset 对象的输出路径均唯一且存在；输出包含 8,948 个 PNG、592 个 OBJ、129 个 Shader 文本、51 个序列化回退文件和 2,633 个运行时 Prefab 对象图。对同一容器路径下多个内部对象，文件名追加 `PathID`，避免对象覆盖。

### 已确认：特殊对象已保留回退数据

- 31 个大型 Spine Prefab 的名称字段含非法 surrogate 字符，已使用 ASCII 安全 JSON 写出，未丢弃引用数据。
- 43 个 Unity 2022 编译 Shader 无法被 UnityPy 的文本导出器完整解码，已保存类型树 JSON 和 `.serialized.bin`。
- 8 个字体图集 Texture2D 没有可解码像素数据，已保存类型树 JSON 和 `.serialized.bin`；对应 Font 对象仍已导出 TTF/OTF。

### 推断：内容导出结果不是原始工程文件

上述输出适合阅读、检索、进一步转换或在 Unity 工程中重建，但不等于开发者原始的 Prefab/Scene YAML、Shader 源码、图片压缩字节或 `.meta` 文件。原始 Bundle 仍以 `.tools/restored_resources_1.2.5/bundles/` 中的字节保持版本为准；内容导出只能作为运行时等价表示。

## 下一步建议

1. 若需要完整资源集，应单独补抓/补下载 166 个 English Audio Bundle，再按 `index/missing_bundle_hashes.json` 校验并追加恢复。
2. 若需要 Unity 工程级文件，基于 `index/assets.json` 和运行时对象图继续做有针对性的 Prefab、Scene、Material 和 Shader 重建；这些结果不能宣称为原始工程文件。
3. 继续分析 `assets_res_dll.bundle` 中的程序集元数据和 `Base.GameUpdate.HybridDllManager` 的实际调用链，确认 HotUpdate 程序集来源。
