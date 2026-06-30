# 劳动法知识图谱 Schema v1

本 Schema 将一条法律规则表示为 n 元超边，而不是简单的“实体—关系—实体”。一条规则同时绑定主体、行为、条件、例外、程序、后果、时效、地域、有效期和原文证据。

## 核心约束

- 每条规则至少包含一个主体、一个法律后果和一份原文证据。
- 每份证据必须包含法律名称、条款号、原文摘录和原始 chunk ID。
- 所有实体引用必须指向图中已定义的实体。
- 生效截止日期不得早于生效起始日期。
- 未在 Schema 中声明的字段一律拒绝，避免抽取模型静默产生脏字段。
- `extraction_confidence` 只表示抽取置信度，不能替代来源校验。

## 文件

- `legal_schema.py`：Pydantic 数据模型与完整性校验。
- `graph_extractor.py`：将法条 chunk 抽取为 Schema，并校验引文和来源。
- `graph_build.py`：逐 chunk 检查点、失败隔离、恢复和图谱聚合。
- `tests/fixtures/legal_graph_golden.json`：三条人工整理的黄金法律规则。
- `tests/fixtures/retrieval_golden.json`：后续混合检索器的最小验收问题。
- `tests/test_legal_schema.py`：Schema 正反向测试。

## 验证

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

## 抽取器用法

```python
from graph_extractor import GraphExtractor

extractor = GraphExtractor(llm, max_retries=2)
graph = extractor.extract_documents(splits)
```

LLM 只产生规则语义。法律名称、条款号、地域、有效期、文件路径及
`chunk_id` 均从现有 `Document.metadata` 或法条原文中获取。模型提供的
`evidence_quote` 必须逐字存在于原文，否则整条抽取结果会被拒绝并重试。

## 在建库流程中运行

先正常生成 chunk 缓存和向量库，同时构建图谱：

```bash
python build_db.py --build-graph
```

已有 `chunks_cache.jsonl` 时，只构建图谱，不重复调用 Embedding：

```bash
python build_db.py --from-cache --graph-only
```

生成文件：

- `graph_chunks.jsonl`：成功抽取的追加式检查点；每个 chunk 成功后立即落盘。
- `graph_failures.jsonl`：失败 chunk、异常类型及来源，失败项下次会重新尝试。
- `legal_graph.json`：当前知识库全部成功结果合并后的 Schema v1 图谱。
- `legal_graph.db`：供桌面端只读查询的规范化 SQLite 图数据库。

重新执行同一命令时，内容指纹未变化的 chunk 会从检查点恢复。只有新增或
内容发生变化的 chunk 才会调用 LLM。需要彻底重建时显式增加
`--reset-graph-checkpoint`。

## 混合检索

`hybrid_retriever.py` 同时使用三类信号：

1. 原有向量库命中的 chunk 及法条引用；
2. 查询中匹配到的法律实体和规则文本；
3. 共享实体连接的一跳或多跳相邻规则。

检索结果经过 RRF 风格排序，并按地域和规则有效期过滤。`backend.py` 启动时若
发现 `legal_graph.db` 会自动启用混合 GraphRAG；数据库不存在或初始化失败时，
会继续使用原有 `SimpleVectorStore`，不影响现有客户端。

## 检索评测

仅评测图检索，不调用 Embedding API：

```bash
python evaluate_retrieval.py --graph-only --k 5
```

评测完整混合检索，并保存逐题结果：

```bash
python evaluate_retrieval.py \
  --graph-db legal_graph.db \
  --vectorstore vectorstore.pkl \
  --k 5 \
  --output retrieval_eval.json
```

报告会对比 `graph_depth=0` 与 `graph_depth=1`，输出 Rule Recall@K、Hit
Rate@K、MRR@K、Citation Precision@K 和 Citation Recall@K。融合权重可通过
`--weight-vector`、`--weight-entity`、`--weight-lexical`、`--weight-graph`
调整，以同一黄金集重复验证。
