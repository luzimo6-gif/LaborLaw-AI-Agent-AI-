# ⚖️ 劳动法 AI 智能助理 (Labor Law AI Agent)

![Version](https://img.shields.io/badge/version-v1.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Framework](https://img.shields.io/badge/framework-NiceGUI%20%7C%20LangGraph-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green.svg)

> 基于多智能体协同 (Multi-Agent) 与现代化桌面 UI 架构构建的专业级劳动法垂直大模型客户端。

---

## 🌟 核心特性 (Key Features)

### 1. 🤖 多智能体深度推演 (Agentic Workflow)
告别单线对话。底层基于 **LangGraph** 构建了包含 `事实梳理员`、`法条检索专员`、`合规审核员` 和 `主编质检员` 的流水线。复杂的案件信息将经过多轮校验，最终输出专业、严谨的分析报告。

### 2. 📖 可视化审计轨迹与 RAG 溯源归因 (Citation & Audit Trail)
打破 LLM 黑盒与幻觉风险：
- **流转可见：** 前端实时展示多智能体节点的推演轨迹。
- **依法有据：** 生成结果内嵌交互式引用上标（如 `[1]`），点击即可弹窗核实具体法条与原始出处。

### 3. 🖥️ 原生级现代桌面体验 (Modern Desktop UI)
彻底摒弃老旧的 Tkinter 界面。采用 **NiceGUI + pywebview** 架构，融合 Google Gemini 的极简通透设计语言：
- **沉浸式 Composer：** 悬浮圆角输入框，支持 `Ctrl+Enter` 快速发送。
- **主题适配：** 全局原生支持暗黑模式 (Dark Mode)，保护视力。
- **纯粹体验：** 打包为独立的 `.exe`，双击即用，无浏览器标签页干扰。

### 4. 🔄 错题本与数据飞轮 (Data Flywheel)
内嵌即时的 👍/👎 反馈机制。遇到逻辑偏差，用户可一键录入纠正意见。系统将自动抓取 `当前上下文 + RAG 检索快照 + 人工修正` 进行结构化沉淀，为后续垂直模型微调（Fine-tune）提供极其珍贵的私有数据。

---

## 🛠️ 技术架构 (Tech Stack)

| 模块 | 技术 |
|------|------|
| GUI | NiceGUI (基于 Quasar & Vue 3) + Tailwind CSS |
| 桌面壳 | pywebview + Microsoft Edge WebView2 |
| LLM | 阿里云 DashScope (qwen-plus) / 兼容 OpenAI 接口 |
| Embedding | text-embedding-v2 / 兼容 OpenAI Embeddings API |
| RAG | LangChain + 自研 SimpleVectorStore (纯 NumPy) |
| 工作流 | LangGraph 多智能体编排 |
| 打包 | PyInstaller |

---

## 🚀 快速开始 (Quick Start)

### 1. 本地开发环境配置

```bash
# 克隆仓库
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME

# 安装依赖
pip install -r requirements.txt

# 启动应用
python gui_nice.py
```

### 2. 配置 API Key

首次启动后，在注册/登录界面配置你的 API Key。支持以下兼容 OpenAI 接口的服务商：

- **阿里云 DashScope (Qwen)：** `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **DeepSeek：** `https://api.deepseek.com`
- **硅基流动 (SiliconFlow)：** `https://api.siliconflow.cn/v1`

### 3. 构建知识库

```bash
# 将法律文档放入 data/ 目录后运行
python build_db.py
```

---

## 📁 项目结构

```
├── gui_nice.py           # NiceGUI 桌面应用入口
├── backend.py            # LangGraph 多智能体引擎
├── simple_vectorstore.py # 纯 NumPy 离线向量存储
├── build_db.py           # 离线建库脚本
├── data/                 # 法律文档库
├── requirements.txt      # Python 依赖
├── version.txt           # 版本号
└── users.json            # 用户数据（首次启动自动创建）
```

---

## 🔒 安全说明

- 密码使用 **PBKDF2 加盐哈希** 存储，兼容旧版 SHA-256 自动升级
- API Key 以用户维度隔离存储，不在代码中硬编码
- SSL 证书验证默认启用，可通过环境变量 `VERIFY_SSL=false` 关闭（仅内网环境）

---

## 📄 License

MIT
