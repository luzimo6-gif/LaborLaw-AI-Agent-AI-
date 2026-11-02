# Python 演示版到 HarmonyOS MVP 的功能映射

## 保留的用户体验

| Python 演示版 | HarmonyOS MVP |
| --- | --- |
| Quick 普法问答 | 普法模式，多轮文字问答与本地法条引用 |
| Pro 案件处理 | 案件模式，改用更直观的中文名称 |
| 右侧智能案件卷宗 | 手机使用抽屉/独立页面，平板和宽窗显示双栏 |
| 六项案件信息 | 案件发生地、单位名称、平均月薪、时间节点、核心诉求、详细经过 |
| 信息完善度 | 本地计算已填写字段比例，达到 60% 后允许生成报告 |
| 对话中自动提取卷宗 | 使用一次结构化模型调用，解析并校验固定 JSON 字段 |
| LangGraph 节点轨迹 | 简化为分阶段进度：整理事实、检索法条、生成建议、复核引用 |
| RAG 引用面板 | 本地检索结果生成引用 ID，回复只能显示通过校验的 ID |
| API 设置 | 设置页配置 Base URL、Model、API Key 和连接测试 |
| 文件上传 | 系统文件选择器；首版支持 TXT、MD、DOCX |
| 报告下载 | 生成可复制、可分享的纯文本/Markdown 报告 |

## 三天 MVP 的简化

原版在运行时依赖 Python、LangGraph、向量检索和多个模型节点。鸿蒙参赛版不直接
搬运这些依赖，而是在 ArkTS 中实现一条可验证的轻量流程：

1. 用户输入问题或案件材料。
2. 在本地知识索引中进行关键词与权重检索。
3. 给检索结果分配本轮临时引用 ID。
4. 将用户问题、卷宗信息、附件文本和法条片段发送给 OpenAI 兼容 API。
5. 校验模型返回的结构和引用 ID，过滤不存在的引用。
6. 展示答案、引用原文和风险提示。

案件报告沿用同一条流程，只是提示词要求输出固定的四部分报告，并在生成前检查
六项卷宗信息。首版不复刻多智能体图和自动重试质检环，以减少编译与调试风险。

## 建议的 ArkTS 代码边界

```text
entry/src/main/ets/
├── entryability/       # UIAbility 生命周期
├── pages/              # 首页、聊天、案件卷宗、设置
├── components/         # 消息气泡、引用卡片、附件条、导航
├── models/             # ChatMessage、CaseFile、Citation、ApiConfig
├── services/           # API、知识检索、附件读取、安全存储
├── stores/             # 应用状态与会话状态
└── utils/              # JSON 校验、错误映射、文本裁剪
```

## 不迁移的桌面版功能

- 用户注册、管理员账号和 `users.json`
- Python/FastAPI/NiceGUI/pywebview 运行环境
- 在线 Embedding、`vectorstore.pkl` 和 GraphRAG
- 反馈数据飞轮
- OCR、扫描 PDF 和图片识别
- Windows EXE 打包逻辑
