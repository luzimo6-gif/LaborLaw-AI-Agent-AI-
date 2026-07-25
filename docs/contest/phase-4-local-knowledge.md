# 第四阶段：本地法律资料与可核验引用

## 目标

把现有资料库的全部 2790 个源文件机械收录为 App 内置只读索引，在不运行
Python、不部署向量数据库和项目服务器的情况下，为普法模式、案件模式和案件报告
提供端侧检索、模型上下文和可核验来源。

## 索引构建

- 源目录保持只读，原始语料不提交到公开仓库
- 收录范围：全国资料 84 份、地方资料 2706 份
- 文档记录：2790
- 正文可检索：2761
- 仅保留文件信息：29
- 条文/文本块：52,903
- App 内索引大小：54,545,066 bytes
- 索引位置：`harmony-app/entry/src/main/resources/rawfile/law_index.json`
- 构建工具：`tools/kb_builder/build_law_index.py`

转换支持 PDF、DOCX、XLSX、OFD，以及经 LibreOffice 成功转换的旧版 Office/WPS；
ZIP 中可识别文字文档也会尝试提取。未进行 OCR、去重、法律效力审查、历史版本
合并、向量化或 GraphRAG。

## App 端能力

- 启动时从 `rawfile` 读取并校验 2790 份文档记录和 52,903 个文本块
- 端侧加权关键词检索，不依赖网络数据库
- 查询包含省市名称时优先返回相应地区资料；未指定地区时轻微优先全国资料
- 对同名重复文件限制候选数量，避免 PDF/DOCX 副本占满引用
- 对欠薪、解除、未签合同和加班等首版高频主题增加核心法条排序权重
- 每次请求默认最多注入 6 条依据，同一文件通常最多 2 条
- 模型只能使用本轮提供的 `[K1]` 等引用编号
- 返回后移除超出本轮候选范围的引用编号
- 每轮回答后展示法规名、条文、原文节选、源 PDF 文件名、状态和生效日期
- 始终显示“资料尚未完成全面法律效力审查”的提示
- 发给模型的消息对象只包含 `role` 和 `content`，本地引用对象不会作为未知字段发送

## 验收

- 日期：2026-07-25
- 索引构建：2790/2790 已收录，其中 2761 份正文可检索
- 核心法条抽样：《中华人民共和国劳动合同法》第八十二条正文与来源匹配
- 完整构建报告：`docs/contest/full-kb-build-report.md`
- ArkTS/HAP 构建：`BUILD SUCCESSFUL in 12 s 283 ms`
- Debug HAP：约 52 MB，未配置正式签名
- HAP 覆盖安装：成功
- 模拟器启动：成功
- 首页状态：`已收录 2790 份，2761 份可检索`
- 启动日志：Ability 内容加载成功，无知识库加载错误
- 真实问题：`公司拖欠工资，我应该如何维权？`
- API 返回：HTTP 200
- 核心检索结果：
  - 《中华人民共和国劳动合同法》第八十五条
  - 《中华人民共和国劳动法》第五十条
  - 《中华人民共和国劳动争议调解仲裁法》第二十七条
- 回答格式：纯文本，无未渲染的 Markdown 标题或加粗标记
- 引用卡片：5 条，法规名、条文、来源文件和状态均正常显示

## 复现命令

```bash
python3 tools/kb_builder/build_law_index.py \
  --scope all \
  --source-root "/path/to/your/legal-corpus" \
  --output harmony-app/entry/src/main/resources/rawfile/law_index.json \
  --report docs/contest/full-kb-build-report.md \
  --soffice /path/to/soffice
```

```bash
NODE_HOME="/Applications/DevEco-Studio.app/Contents/tools/node" \
DEVECO_SDK_HOME="/Applications/DevEco-Studio.app/Contents/sdk" \
JAVA_HOME="/Applications/DevEco-Studio.app/Contents/jbr/Contents/Home" \
/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw \
  assembleHap --mode module \
  -p module=entry@default -p product=default -p buildMode=debug --no-daemon
```
