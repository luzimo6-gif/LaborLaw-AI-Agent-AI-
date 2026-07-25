# HarmonyOS 本地法律索引转换器

转换器默认读取资料目录中的全部文件，并生成可随 HAP 发布的紧凑 JSON 索引。

先安装独立的转换器依赖：

```bash
python3 -m pip install -r tools/kb_builder/requirements.txt
```

```bash
python3 tools/kb_builder/build_law_index.py \
  --source-root "/path/to/your/legal-corpus" \
  --output harmony-app/entry/src/main/resources/rawfile/law_index.json \
  --report docs/contest/full-kb-build-report.md \
  --soffice /path/to/soffice
```

行为边界：

- `--scope all`（默认）包含全国与地方目录中的全部源文件。
- `--scope core` 可回归验证原来的 84 份全国性 PDF。
- 支持 PDF、DOCX、XLSX、OFD；旧版 DOC/XLS/WPS 通过 LibreOffice
  转换后提取；ZIP 中可识别的文字文档也会尝试提取。
- 无法提取正文的文件仍保留元数据，并在构建报告中逐项列出。
- 优先按条文切分，不含条文编号的文件按长度机械分段。
- 不执行 OCR、向量化、模型调用、去重、失效清理或版本合并。
- 原始文件保持只读，生成物只写入项目目录。
- 生成索引前请确认你有权处理和再分发相应资料。
