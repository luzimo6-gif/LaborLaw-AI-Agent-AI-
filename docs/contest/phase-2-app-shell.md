# 第二阶段：原生应用外壳验收

## 目标

使用 ArkTS/ArkUI 建立参赛版的核心页面和导航，保留原 Python 演示版的
普法模式、案件模式和智能卷宗认知模型，并为后续 API、附件和知识库接入预留入口。

## 已实现

- [x] 普法模式首页和四个常见问题快捷入口
- [x] 普法咨询文本输入、附件入口和发送按钮状态
- [x] 案件模式引导、案件材料入口和完整度展示
- [x] 六项智能卷宗：地点、单位、薪资、时间、诉求、详细经过
- [x] 卷宗完整度本地计算，达到 60% 后启用报告按钮
- [x] Base URL、模型名称、API Key 和连接测试的设置界面
- [x] 普法、案件、卷宗、设置四项悬浮底部导航
- [x] Phone/Tablet 设备声明
- [x] 宽屏案件对话与卷宗双栏布局代码
- [x] 隐私说明和法律效力核对提示

## 验收结果

- 日期：2026-07-25
- ArkTS/HAP 构建：`BUILD SUCCESSFUL`
- ArkUI PreviewBuild：`BUILD SUCCESSFUL`
- Phone Previewer：普法、案件、卷宗、设置四页均正常渲染和切换
- HarmonyOS 模拟器：`LaborLawAI_API23` 已启动并通过 HDC 连接
- HAP 安装：成功
- 应用启动：`com.laborlaw.aiassistant/EntryAbility` 启动成功
- 视觉验收：普法模式首页、免责声明、问题建议、输入区、附件入口和底部导航
  均在 1260 × 2720 模拟器画面中正常显示
- HAP：`entry/build/default/outputs/default/entry-default-unsigned.hap`

## 本阶段边界

本阶段是可交互原生界面，不发送网络请求，也不持久化真实 API Key。以下能力留给
后续阶段：

1. OpenAI 兼容 API 客户端、连接测试、超时和错误映射。
2. API 配置的本机安全存储。
3. 多轮消息状态和真实模型回复。
4. TXT/MD、DOCX 文件选择与文本读取。
5. 本地法律知识索引、检索和引用 ID 校验。
6. 服务卡片和最终签名安装测试。
