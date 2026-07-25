# 第一阶段：开发环境与空工程验收

## 目标

在 Mac ARM 环境安装官方稳定版 DevEco Studio，使用 IDE 自带模板创建
Stage 模型 ArkTS/ArkUI 工程，并完成空 HAP 的构建和 Previewer 启动。

## 当前环境

- 主机：Apple Silicon MacBook（ARM64）
- 操作系统：macOS 26.5.2
- 工作区：`harmony-app/`
- DevEco Studio：6.1.0 Release，Build 6.1.0.860（Mac ARM）
- SDK/API：HarmonyOS 6.1.0 (23)
- Hvigor：6.23.7
- 运行架构：HarmonyOS 原生应用直接调用用户配置的 OpenAI 兼容 API
- 项目自有服务器：不需要

## 创建原则

1. 使用 DevEco Studio 的 Empty Ability 模板，不手工猜测 Hvigor、SDK 或
   插件版本。
2. 选择 ArkTS、Stage 模型和 Phone/Tablet 设备类型。
3. Bundle Name 暂定为 `com.laborlaw.aiassistant`，如比赛规则要求再调整。
4. 工程创建后立即执行一次干净构建，不先加入业务代码。
5. 首次构建通过后再实现导航、普法模式和案件模式。

## 空工程验收记录

以下项目将在 DevEco Studio 安装后填写：

- [x] DevEco Studio 安装完成
- [x] HarmonyOS SDK 安装完成
- [x] `harmony-app/` 工程由官方 Empty Ability 模板创建
- [x] Hvigor 依赖解析成功
- [x] Debug HAP 构建成功
- [x] ArkUI Previewer 启动成功
- [x] 首页能够在 Phone Previewer 正常显示

## 首次构建结果

- 构建日期：2026-07-25
- 命令：`tools/harmony/build-debug.sh`
- 结果：`BUILD SUCCESSFUL`
- 产物：`entry/build/default/outputs/default/entry-default-unsigned.hap`
- 产物大小：约 128 KB
- 签名：未配置，因此当前产物为 unsigned HAP；空工程编译验收不受影响

命令行构建必须显式使用 DevEco Studio 自带的 Node、HarmonyOS SDK 和 JDK。
仓库中的脚本已封装这些路径，避免依赖 Mac 的全局 Java 或 Node 环境。

## 首次运行结果

- 运行方式：DevEco Studio ArkUI Previewer（Phone）
- 页面：`entry/src/main/ets/pages/Index.ets`
- 结果：默认首页正常渲染并显示 `Hello World`
- 结论：空工程已经满足“可同步、可编译、可预览”的第一阶段验收条件

## 模拟器验收

- 验收日期：2026-07-25
- 模拟器：`LaborLawAI_API23`
- 系统：HarmonyOS 6.1.0 (API 23)
- 配置：Phone、ARM64、4 核、2 GB RAM、6 GB 存储
- 设备连接：HDC 已识别 `127.0.0.1:5555`
- HAP 安装：成功
- `EntryAbility` 启动：成功
- 页面显示：应用首页在模拟器中完整渲染

## 已知说明

- 官方下载页中 Mac ARM 的 DevEco Studio 6.1.1.290 当前显示为不可下载，
  因此第一阶段使用同为 6.1 Release 系列且可下载的 6.1.0.860。
- Device Manager 的设备列表界面仍可能停留在“等待数据加载中”，但本地模拟器
  镜像、官方 Emulator CLI 和 HDC 均工作正常，不影响当前开发和演示。
- 签名文件、API Key、本机 SDK 路径和 DevEco Studio 缓存不得提交到 Git。
- API Key 仅在应用设置页由使用者输入，后续使用 HarmonyOS 安全存储保存。
