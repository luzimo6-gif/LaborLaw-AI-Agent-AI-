# 第六阶段：HarmonyOS 特性

## 参赛版已集成能力

### 1. Form Kit 桌面服务卡片

- 卡片名称：劳动权益速查
- 卡片规格：2×2 ArkTS 动态卡片
- 展示内容：欠薪、未签合同、违法解除、加班四类高频入口，以及 2790 份本地资料状态
- 交互：点击卡片任意区域，通过 `router` 卡片事件打开 `EntryAbility`
- 卡片提供方：`LawFormAbility`
- 卡片页面：`LawQuickCard.ets`

系统验证结果：

- `FormMgr` 已注册 `com.laborlaw.aiassistant / LawFormAbility / LawQuickCard`。
- 系统卡片中心能够搜索到“劳动法 AI 助手”和“劳动权益速查”。
- 2×2 预览文字完整，无标题和按钮截断。
- “添加至桌面”成功，桌面卡片显示正常。
- 点击桌面卡片能够进入应用普法首页。

### 2. UI Design Kit 沉浸光感页签

- 基于 HarmonyOS 6.1（API 23）的 `@kit.UIDesignKit`，使用官方
  `HdsTabs` 和 `barFloatingStyle()`，承载普法、案件、卷宗、设置四个核心区。
- 系统材质采用 `MaterialType.IMMERSIVE` 与
  `MaterialLevel.EXQUISITE`，并启用金色 `lightColor`、渐变遮罩和温控降级。
- 保留自定义页签内容和选中状态，通过 `HdsTabsController` 与
  `onChange` 同步页面状态。
- 采用内容不穿入页签栏的布局，避免高信息密度表单在透明材质中产生重影，
  同时保留官方沉浸材质与选中光感。

系统验证结果：

- HarmonyOS 6.1（API 23）手机模拟器编译、安装和启动成功。
- 普法、案件、卷宗、设置四个页签均可点击切换，标题和选中光感同步变化。
- 页签区未遮挡咨询输入框、案件材料按钮及系统手势导航区。

官方参考：

- [HarmonyOS 6.1 UI Design Kit：悬浮页签与沉浸光感](https://developer.huawei.com/consumer/cn/monthly/202604?ha_source=202604yk&ha_sourceId=89000503)

### 2.1 暖色空间化视觉系统

- 采用“米白纸感 + 暖橙 + 雾青”的统一配色，弱化传统政务应用的冰冷感，
  同时保持法律服务所需的清晰度与可信度。
- 首页以暖色山水桥梁作为无文字背景素材，标题、咨询框、操作按钮和数据状态
  均使用原生 ArkUI 渲染，不以整张效果图代替可交互界面。
- 普法、案件、卷宗、设置四个页签采用同一张山水背景、同一高度和同一标题布局，
  仅根据页面切换标题与副标题，避免跨页时产生视觉割裂。
- 标题固定在素材预留的左侧浅色区域，右侧太阳、桥梁与城市轮廓不会干扰文字；
  不再使用含义不明确的单字品牌标识。
- 咨询入口使用带细描边、柔和阴影和高光边缘的悬浮卡片；案件流程被表达为
  “咨询—梳理—报告”三个空间层级。
- 工资拖欠、被公司辞退、没有劳动合同、加班费争议采用暖橙与雾青交替的
  触感卡片，点击后会将对应问题填入咨询框。
- 本地法规面板直接展示 2790 份法规和 2761 份可检索资料，并强调
  “专业可靠、隐私安全、本地检索”。
- 山水主视觉素材：`entry/src/main/resources/base/media/hero_warm_bridge.png`。

模拟器验证结果：

- 长页面可正常滚动，第二行场景卡、知识库状态和免责声明均完整显示。
- 预设问题填充后，咨询按钮能够按状态由禁用变为可用。
- 普法与案件页切换后，标题、页面内容和沉浸光感选中状态保持同步。

### 3. 一次开发、多端自适应布局

- 工程声明支持 `phone` 和 `tablet`。
- 页面宽度达到 720vp 时切换宽屏布局。
- 普法高频入口由两列变为四列。
- 案件模式在宽屏下采用“对话 + 卷宗”双栏布局，手机端保持单栏。
- 设置页和主要内容设置最大宽度，避免平板上文本行过长。

### 4. Asset Store Kit 安全存储

- API Key 使用 HarmonyOS Asset Store Kit 保存。
- Key 设置为设备首次解锁后可访问，并明确禁止跨设备同步。
- Base URL 和模型名称使用 Preferences 保存，密钥不写入 Preferences、代码或本地知识索引。

### 5. Core File Kit 系统文件选择器

- TXT、MD、DOCX 均通过系统 DocumentViewPicker 由用户主动选择。
- 应用只读取用户授予的 URI，不申请笼统的全盘文件权限。

## 相关文件

- `entry/src/main/ets/lawformability/LawFormAbility.ets`
- `entry/src/main/ets/lawcard/pages/LawQuickCard.ets`
- `entry/src/main/resources/base/profile/form_config.json`
- `entry/src/main/module.json5`
- `entry/src/main/ets/pages/Index.ets`
- `entry/src/main/ets/services/ConfigStore.ets`
- `entry/src/main/ets/services/AttachmentService.ets`

## 验收边界

- 当前只有一台手机模拟器，因此手机卡片、点击跳转和宽度切换逻辑已验证；
  平板真实设备或平板模拟器的最终视觉验收后续补做。
- 本阶段实现的是标准服务卡片，不包含出框实时动效；若比赛准备时间允许，
  可在后续版本将其升级为互动卡片。
- Debug HAP 尚未配置正式签名，当前产物用于模拟器与开发调试。
