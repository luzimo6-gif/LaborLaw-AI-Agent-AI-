#!/usr/bin/env python3
"""
build_db.py — 离线知识库建库脚本（独立运行，工业级）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
流水线架构（6 个 Phase）：
  Phase 1  目录扫描      → 收集全部 .pdf/.docx 文件路径
  Phase 2  多线程加载    → ThreadPoolExecutor + tqdm，60s 超时兜底
  Phase 3  法条正则切分  → LegalRegexSplitter（地域识别 + 章/节/条层级）
  Phase 4  JSONL 缓存    → chunks_cache.jsonl（断点续传）
  Phase 5  并发 Embedding → ConcurrentDashScopeEmbeddings 分批入库
  Phase 6  验证 & 报告   → 确认入库条数
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用法：
    python build_db.py                        # 完整建库
    python build_db.py --from-cache           # 跳过 Phase 1~4，直接从 JSONL → Embedding → 入库
    python build_db.py --workers-load 4 --workers-embed 8
    python build_db.py --batch-size 300       # 自定义 ChromaDB 批次大小

依赖：
    pip install langchain langchain-community pymupdf docx2txt requests tqdm urllib3
"""

import os
import sys
import io
# 强制 stdout 使用 UTF-8，避免 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
import json
import glob
import time
import queue
import signal
import threading
import re
import argparse
import traceback
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================================================================
# 全局中断标志（线程安全）
# ================================================================
_interrupted = threading.Event()

def _signal_handler(signum, frame):
    print("\n\n[中断] 收到 Ctrl+C，正在安全退出（已入库数据不受影响）...")
    _interrupted.set()

signal.signal(signal.SIGINT, _signal_handler)

# ================================================================
# 0. 常量与配置
# ================================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CACHE_FILE = os.path.join(SCRIPT_DIR, "chunks_cache.jsonl")
VECTORSTORE_PATH = os.path.join(SCRIPT_DIR, "vectorstore.pkl")  # SimpleVectorStore pickle 文件

# ── 大模型 API ──
# API_KEY 优先从环境变量读取，其次从 .env 文件加载
import os as _os
API_KEY = _os.getenv("DASHSCOPE_API_KEY", "")
if not API_KEY:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(SCRIPT_DIR, ".env"))
        API_KEY = _os.getenv("DASHSCOPE_API_KEY", "")
    except ImportError:
        pass
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMBED_MODEL = "text-embedding-v2"
EMBED_DIM = 1536                          # text-embedding-v2 输出维度



# ── 并发参数 ──
MAX_WORKERS_LOAD = 4                      # 文件加载并发数
MAX_WORKERS_EMBED = 8                     # Embedding API 并发数
EMBED_TEXTS_PER_REQUEST = 20              # 每次 API 请求发送的文本条数
CHROMA_BATCH_SIZE = 300                   # 每批写入的 chunk 数（用于嵌入分批）
LOAD_TIMEOUT = 60                         # 单文件加载超时秒数

# ── 目录 → 分类映射 ──
CATEGORY_MAPPING = {
    "法律":               "National Laws",
    "地方法律 法规规章":   "Local Regulations",
    "行政法规":           "Administrative Regulations",
    "规章及法律规范":     "Rules and Norms",
}

# SSL 证书验证：默认启用，设置环境变量 VERIFY_SSL=false 可禁用
import urllib3
if os.environ.get("VERIFY_SSL", "true").lower() == "false":
    urllib3.disable_warnings()


# ================================================================
# 1. 文件加载器（三级降级 + 60 秒超时）
# ================================================================

def load_single_file(file_path: str, category: str, timeout: int = LOAD_TIMEOUT) -> List:
    """
    加载单个文件 → 返回 LangChain Document 列表。

    加载链：
      PDF  → PyMuPDFLoader（纯 Python，无需外部依赖）
      DOCX → docx2txt.process()（纯 Python，不依赖 LibreOffice/MS Office）

    超时保护：每级方案均被 threading.Thread + queue.Queue 包裹，
    超时 60 秒后自动跳过该文件并打印警告，绝不死锁。
    """
    from langchain_core.documents import Document
    from langchain_community.document_loaders import PyMuPDFLoader

    docs: List[Document] = []
    file_name = os.path.basename(file_path)

    # ────────── PDF 处理 ──────────
    if file_path.endswith('.pdf'):
        result_queue: queue.Queue = queue.Queue()

        def _load_pdf():
            try:
                loader = PyMuPDFLoader(file_path)
                loaded = loader.load()
                for d in loaded:
                    d.metadata["category"] = category
                    d.metadata["file_type"] = ".pdf"
                    d.metadata["source"] = file_path
                result_queue.put(("success", loaded))
            except Exception as e:
                result_queue.put(("error", str(e)))

        t = threading.Thread(target=_load_pdf, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            print(f"  [超时跳过] {file_name}: 处理超过 {timeout}s")
            return docs

        try:
            status, loaded_docs = result_queue.get_nowait()
            if status == "success":
                docs.extend(loaded_docs)
                print(f"  [OK] PDF: {file_name} ({len(loaded_docs)} 页)")
            else:
                print(f"  [失败] {file_name}: {loaded_docs}")
        except queue.Empty:
            pass
        return docs

    # ────────── DOCX 处理 ──────────
    if file_path.endswith('.docx'):
        result_queue: queue.Queue = queue.Queue()

        def _load_docx():
            try:
                import docx2txt
                txt = docx2txt.process(file_path)
                if txt and len(txt.strip()) > 10:
                    doc = Document(
                        page_content=txt,
                        metadata={
                            "category": category,
                            "file_type": ".docx",
                            "source": file_path,
                        }
                    )
                    result_queue.put(("success", doc, len(txt)))
                else:
                    result_queue.put(("empty", None, 0))
            except Exception as e:
                result_queue.put(("error", None, str(e)))

        t = threading.Thread(target=_load_docx, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            print(f"  [超时跳过] {file_name}: 处理超过 {timeout}s")
            return docs

        try:
            status, doc, txt_len = result_queue.get_nowait()
            if status == "success":
                docs.append(doc)
                print(f"  [OK] DOCX: {file_name} ({txt_len} 字符)")
            elif status == "empty":
                print(f"  [跳过] {file_name}: 文档内容为空")
            else:
                print(f"  [失败] {file_name}: {txt_len}")
        except queue.Empty:
            pass
        return docs

    # 不支持的文件格式
    if not docs:
        print(f"  [跳过] {file_name}: 不支持的文件格式")
    return docs


# ================================================================
# 2. 目录扫描器
# ================================================================

def scan_files(data_dir: str = DATA_DIR) -> List[Tuple[str, str]]:
    """
    递归扫描 data/ 目录，返回去重后的 [(file_path, category), ...]

    支持 4 个子目录 + 根目录散落文件的自动分类。
    """
    if not os.path.exists(data_dir):
        print(f"[ERROR] 数据目录不存在: {data_dir}")
        return []

    file_list: List[Tuple[str, str]] = []
    extensions = ["*.pdf", "*.docx"]

    # 1) 根目录散落文件
    for ext in extensions:
        for fp in glob.glob(os.path.join(data_dir, ext)):
            file_list.append((fp, "General Documents"))

    # 2) 子目录按分类映射
    for subdir_name in os.listdir(data_dir):
        subdir_path = os.path.join(data_dir, subdir_name)
        if not os.path.isdir(subdir_path):
            continue
        category = CATEGORY_MAPPING.get(subdir_name, subdir_name)
        for ext in extensions:
            for fp in glob.glob(os.path.join(subdir_path, "**", ext), recursive=True):
                file_list.append((fp, category))

    # 去重（按绝对路径）
    seen = set()
    unique = []
    for fp, cat in file_list:
        fp_abs = os.path.abspath(fp)
        if fp_abs not in seen:
            seen.add(fp_abs)
            unique.append((fp, cat))

    if len(unique) < len(file_list):
        print(f"  → 去重: {len(file_list)} → {len(unique)} 个文件")

    return unique


# ================================================================
# 3. LegalRegexSplitter（法律文档正则切分 + 地域识别）
# ================================================================

class LegalRegexSplitter:
    """
    专为中国法律文档定制的正则切分器。

    功能：
      1. 从文件名中提取省市标签  →  metadata["region"]
      2. 正则匹配「第X章」「第X节」「第X条」→  保持层级结构
      3. 无章节格式时自动回退为 RecursiveCharacterTextSplitter
    """

    REGIONS: List[str] = [
        "北京", "上海", "天津", "重庆",
        "广东", "江苏", "浙江", "山东", "河南", "四川", "湖北", "湖南",
        "河北", "安徽", "辽宁", "福建", "陕西", "江西", "黑龙江",
        "广西", "云南", "贵州", "山西", "吉林", "内蒙古",
        "新疆", "甘肃", "海南", "宁夏", "青海", "西藏",
        "深圳", "广州",
    ]

    def split_documents(self, documents: List) -> List:
        from langchain_core.documents import Document

        # ── 回退切分器 ──
        fallback_splitter = None
        try:
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            fallback_splitter = RecursiveCharacterTextSplitter(
                chunk_size=500,
                chunk_overlap=50,
                separators=["\n\n", "\n", "。", "；"],
            )
        except ImportError:
            pass

        # ── 1) 按 source 合并文本 ──
        source_map: Dict[str, Dict] = {}
        for doc in documents:
            src = doc.metadata.get("source", "未知法律文件")
            cat = doc.metadata.get("category", "未分类")
            if src not in source_map:
                source_map[src] = {"text": "", "category": cat}
            source_map[src]["text"] += doc.page_content + "\n\n"

        final_chunks: List[Document] = []

        # ── 2) 逐文件切分 ──
        for source, data in source_map.items():
            text = data["text"]
            category = data["category"]

            # 地域识别
            ext = os.path.splitext(source)[1]
            law_name = os.path.basename(source).replace(ext, "")
            doc_region = "全国"
            for r in self.REGIONS:
                if r in law_name:
                    doc_region = r
                    break

            chunks_before = len(final_chunks)

            # 预处理：合并跨行续写
            text = re.sub(
                r'(?<=[^。；：？！\n])\n(?![（\(][一二三四五六七八九十]+[）\)]|\d+\.)',
                '', text
            )

            lines = text.split('\n')
            current_chapter = ""
            current_section = ""
            current_article_text = ""

            chapter_pat = re.compile(r'^第[一二三四五六七八九十百]+章\s+(.*)')
            section_pat = re.compile(r'^第[一二三四五六七八九十百]+节\s+(.*)')
            article_pat = re.compile(r'^(第[一二三四五六七八九十百千万]+条[\s、，。])(.*)')

            def _save_article():
                nonlocal current_article_text
                if len(current_article_text.strip()) > 10:
                    hierarchy = f"《{law_name}》"
                    if current_chapter:
                        hierarchy += f" [{current_chapter}]"
                    if current_section:
                        hierarchy += f" [{current_section}]"
                    final_chunks.append(Document(
                        page_content=f"{hierarchy}\n{current_article_text.strip()}",
                        metadata={
                            "source":   source,
                            "law_name": law_name,
                            "category": category,
                            "chapter":  current_chapter,
                            "region":   doc_region,
                        }
                    ))
                current_article_text = ""

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if chapter_pat.match(line):
                    current_chapter = line
                    current_section = ""
                    continue
                if section_pat.match(line):
                    current_section = line
                    continue
                m = article_pat.match(line)
                if m:
                    _save_article()
                    current_article_text = line
                else:
                    if current_article_text:
                        current_article_text += f"\n{line}"

            _save_article()

            # ── 3) 无章节格式时的回退 ──
            if len(final_chunks) == chunks_before:
                if fallback_splitter:
                    fb_docs = fallback_splitter.create_documents(
                        [text],
                        metadatas=[{
                            "source":   source,
                            "law_name": law_name,
                            "category": category,
                            "chapter":  "SimpleChunk",
                            "region":   doc_region,
                        }]
                    )
                    for fb in fb_docs:
                        fb.page_content = f"《{law_name}》\n{fb.page_content}"
                        final_chunks.append(fb)
                else:
                    for para in text.split('\n\n'):
                        if len(para.strip()) > 10:
                            final_chunks.append(Document(
                                page_content=f"《{law_name}》\n{para.strip()}",
                                metadata={
                                    "source":   source,
                                    "law_name": law_name,
                                    "category": category,
                                    "chapter":  "SimpleChunk",
                                    "region":   doc_region,
                                }
                            ))

        return final_chunks


# ================================================================
# 4. ConcurrentDashScopeEmbeddings（并发 Embedding，完整异常兜底）
# ================================================================

from langchain.embeddings.base import Embeddings


class ConcurrentDashScopeEmbeddings(Embeddings):
    """
    多线程并发调用 DashScope text-embedding-v2 API。

    关键设计：
      • 每轮 HTTP 请求携带 {texts_per_request} 条文本（减少 API 往返）
      • ThreadPoolExecutor 并发发送请求（默认 8 线程）
      • HTTP 超时 / 429 限流 / 连接异常 → 自动退避重试（默认 2 次）
      • 彻底失败 → 兜底返回 1536 维零向量（不崩溃、不丢失数据）
      • 继承 langchain.embeddings.base.Embeddings，通过 ChromaDB isinstance 类型检查
    """

    def __init__(
        self,
        api_key: str = API_KEY,
        base_url: str = BASE_URL,
        model: str = EMBED_MODEL,
        max_workers: int = MAX_WORKERS_EMBED,
        texts_per_request: int = EMBED_TEXTS_PER_REQUEST,
        retries: int = 2,
    ):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_workers = max_workers
        self.texts_per_request = texts_per_request
        self.retries = retries

        # 复用 Session（连接池 + Keep-Alive）
        import requests as _requests
        self._requests = _requests
        self._session = _requests.Session()
        self._session.verify = os.environ.get("VERIFY_SSL", "true").lower() != "false"

        # 线程安全打印锁
        self._print_lock = threading.Lock()

    def _log(self, msg: str):
        """线程安全打印"""
        with self._print_lock:
            print(msg, flush=True)

    def _embed_batch(
        self, texts: List[str], batch_idx: int
    ) -> Tuple[int, List[List[float]]]:
        """
        发送一个批次的 embedding 请求。
        返回 (batch_idx, [[float, ...], ...])

        重试策略：
          429 (限流)  → sleep 3/6/9 秒递增
          超时/连接错误 → sleep 2/4 秒
          最终失败     → 零向量兜底
        """
        url = f"{self.base_url}/embeddings"
        payload = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(self.retries + 1):
            try:
                resp = self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=120,
                )

                # ── 200 成功 ──
                if resp.status_code == 200:
                    body = resp.json()
                    if "data" in body:
                        items = sorted(body["data"], key=lambda x: x["index"])
                        embs = [it["embedding"] for it in items]
                        return batch_idx, embs
                    else:
                        self._log(
                            f"  [WARN] Embed batch#{batch_idx}: 200 但无 data 字段 → "
                            f"零向量兜底 ({len(texts)} 条)"
                        )
                        return batch_idx, [[0.0] * EMBED_DIM] * len(texts)

                # ── 429 限流 ──
                elif resp.status_code == 429:
                    if attempt < self.retries:
                        delay = 3 * (attempt + 1)
                        self._log(
                            f"  [限流] Embed batch#{batch_idx}: HTTP 429 → "
                            f"等待 {delay}s 后重试 (第 {attempt+1}/{self.retries+1} 次)"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        self._log(
                            f"  [放弃] Embed batch#{batch_idx}: 429 重试 {self.retries} 次仍失败 → "
                            f"零向量兜底 ({len(texts)} 条)"
                        )
                        return batch_idx, [[0.0] * EMBED_DIM] * len(texts)

                # ── 其他 HTTP 错误 ──
                else:
                    if attempt < self.retries:
                        self._log(
                            f"  [重试] Embed batch#{batch_idx}: HTTP {resp.status_code} → "
                            f"等待 2s (第 {attempt+1}/{self.retries+1} 次)"
                        )
                        time.sleep(2)
                        continue
                    else:
                        self._log(
                            f"  [放弃] Embed batch#{batch_idx}: HTTP {resp.status_code} "
                            f"重试 {self.retries} 次仍失败 → 零向量兜底 ({len(texts)} 条)"
                        )
                        return batch_idx, [[0.0] * EMBED_DIM] * len(texts)

            except self._requests.exceptions.Timeout:
                if attempt < self.retries:
                    self._log(
                        f"  [超时] Embed batch#{batch_idx}: 请求超时 → "
                        f"等待 2s (第 {attempt+1}/{self.retries+1} 次)"
                    )
                    time.sleep(2)
                    continue
                else:
                    self._log(
                        f"  [放弃] Embed batch#{batch_idx}: 超时 {self.retries} 次 → "
                        f"零向量兜底 ({len(texts)} 条)"
                    )
                    return batch_idx, [[0.0] * EMBED_DIM] * len(texts)

            except self._requests.exceptions.ConnectionError as e:
                if attempt < self.retries:
                    self._log(
                        f"  [连接] Embed batch#{batch_idx}: 连接错误 → "
                        f"等待 2s (第 {attempt+1}/{self.retries+1} 次) | {e}"
                    )
                    time.sleep(2)
                    continue
                else:
                    self._log(
                        f"  [放弃] Embed batch#{batch_idx}: 连接失败 → 零向量兜底"
                    )
                    return batch_idx, [[0.0] * EMBED_DIM] * len(texts)

            except Exception as e:
                if attempt < self.retries:
                    self._log(
                        f"  [异常] Embed batch#{batch_idx}: {type(e).__name__} → "
                        f"等待 2s (第 {attempt+1}/{self.retries+1} 次)"
                    )
                    time.sleep(2)
                    continue
                else:
                    self._log(
                        f"  [放弃] Embed batch#{batch_idx}: {type(e).__name__}: {e} → "
                        f"零向量兜底"
                    )
                    return batch_idx, [[0.0] * EMBED_DIM] * len(texts)

        # 理论上不会执行到这
        return batch_idx, [[0.0] * EMBED_DIM] * len(texts)

    def embed_documents(
        self, texts: List[str], show_progress: bool = True
    ) -> List[List[float]]:
        """
        并发 Embedding 全部文本。

        流程：
          1. 将 texts 切分为多个 batch（每批 texts_per_request 条）
          2. ThreadPoolExecutor 并发发送 API 请求
          3. 按 batch_idx 归并结果，保证顺序
          4. 截断到原始 lengths
        """
        if not texts:
            return []

        # 切分 batch
        batches: List[Tuple[int, List[str]]] = []
        for i in range(0, len(texts), self.texts_per_request):
            batch_texts = texts[i:i + self.texts_per_request]
            batch_idx = i // self.texts_per_request
            batches.append((batch_idx, batch_texts))

        total_batches = len(batches)
        print(
            f"\n[Embedding] 共 {total_batches} 批次，"
            f"每批 ≤{self.texts_per_request} 条，{self.max_workers} 线程并发"
        )

        # 进度条
        try:
            from tqdm import tqdm
            pbar = tqdm(
                total=total_batches, desc="API Embedding", unit="batch",
                disable=not show_progress,
            )
        except ImportError:
            pbar = None

        # 结果字典（batch_idx → embeddings）
        results: Dict[int, List[List[float]]] = {}
        embed_start = time.time()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._embed_batch, bt, bidx): bidx
                for bidx, bt in batches
            }
            for future in as_completed(futures):
                if _interrupted.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    bidx, embs = future.result(timeout=150)
                    results[bidx] = embs
                except Exception as e:
                    # 处理 future 自身的异常
                    bidx = futures[future]
                    self._log(f"  [FUTURE] batch#{bidx} 内部崩溃: {e}")
                    # 找到对应的 batch 文本数量
                    for _bidx, bt in batches:
                        if _bidx == bidx:
                            results[bidx] = [[0.0] * EMBED_DIM] * len(bt)
                            break
                if pbar:
                    pbar.update(1)

        if pbar:
            pbar.close()

        embed_elapsed = time.time() - embed_start
        print(f"[Embedding] 完成，耗时 {embed_elapsed:.1f}s")

        # 按 batch_idx 顺序拼接
        all_embeddings: List[List[float]] = []
        for i in range(total_batches):
            if i in results:
                all_embeddings.extend(results[i])
            else:
                # 缺失的 batch，补零向量
                for _bidx, bt in batches:
                    if _bidx == i:
                        all_embeddings.extend([[0.0] * EMBED_DIM] * len(bt))
                        break

        # 截断到原始 texts 长度（最后一批可能不足 texts_per_request）
        return all_embeddings[:len(texts)]

    def embed_query(self, text: str) -> List[float]:
        """单条查询 Embedding"""
        _, embs = self._embed_batch([text], 0)
        return embs[0] if embs else [0.0] * EMBED_DIM


# ================================================================
# 5. JSONL 缓存读写（断点续传核心）
# ================================================================

def save_chunks_to_jsonl(chunks: List, cache_path: str = CACHE_FILE):
    """
    将 Document 列表序列化为 JSONL。
    每行一条 JSON，字段：{"page_content": str, "metadata": dict}
    """
    print(f"\n[缓存] 写入 {len(chunks)} 条 chunk → {cache_path} ...")
    start = time.time()
    written = 0
    with open(cache_path, 'w', encoding='utf-8') as f:
        for ch in chunks:
            f.write(json.dumps({
                "page_content": ch.page_content,
                "metadata": ch.metadata,
            }, ensure_ascii=False) + "\n")
            written += 1
    elapsed = time.time() - start
    size_mb = os.path.getsize(cache_path) / (1024 * 1024)
    print(f"[缓存] 写入 {written} 条，耗时 {elapsed:.1f}s，{size_mb:.1f} MB")


def load_chunks_from_jsonl(cache_path: str = CACHE_FILE) -> List:
    """
    从 JSONL 缓存恢复 Document 列表。
    遇到破损行打印警告并跳过，不中断整体恢复。
    """
    from langchain_core.documents import Document

    if not os.path.exists(cache_path):
        print(f"[缓存] 文件不存在: {cache_path}")
        return []

    print(f"\n[缓存] 从 {cache_path} 恢复 chunks ...")
    start = time.time()
    chunks: List[Document] = []
    skipped = 0

    with open(cache_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                chunks.append(Document(
                    page_content=record["page_content"],
                    metadata=record.get("metadata", {}),
                ))
            except (json.JSONDecodeError, KeyError) as e:
                skipped += 1
                if skipped <= 5:
                    print(f"  [WARN] 第 {line_num} 行损坏: {e}")

    elapsed = time.time() - start
    print(f"[缓存] 恢复 {len(chunks)} 条 chunk（跳过 {skipped} 条损坏），耗时 {elapsed:.1f}s")
    return chunks


# ================================================================
# 6. ChromaDB 分批写入（每批强制 persist，Ctrl+C 安全）
# ================================================================

def write_to_simple_vs(
    chunks: List,
    embedder: ConcurrentDashScopeEmbeddings,
    vs_path: str = VECTORSTORE_PATH,
    batch_size: int = CHROMA_BATCH_SIZE,
):
    """
    分批写入 SimpleVectorStore (pickle 持久化)。

    关键保障：
      • 每批 add_documents() 后立即 save() 落盘
      • 即使被 Ctrl+C 强杀，已落盘数据绝对安全
      • 第一批用 from_documents 创建库，后续用 add_documents 追加
    """
    from simple_vectorstore import SimpleVectorStore

    if not chunks:
        print("[WARN] 没有 chunk，跳过入库")
        return None

    # 清空旧库
    if os.path.exists(vs_path):
        print(f"[清理] 删除旧库: {vs_path}")
        os.remove(vs_path)

    total = len(chunks)
    num_batches = (total + batch_size - 1) // batch_size
    print(f"\n[SimpleVS] {total} 个 chunk → {num_batches} 批（每批 ≤{batch_size}）")

    try:
        from tqdm import tqdm
        pbar = tqdm(total=total, desc="VectorStore 入库", unit="chunk")
    except ImportError:
        pbar = None

    vectorstore = None
    written = 0

    for batch_no in range(num_batches):
        if _interrupted.is_set():
            print(f"\n[中断] 用户取消，已入库 {written}/{total} 个 chunk → 数据安全")
            break

        i = batch_no * batch_size
        batch = chunks[i:i + batch_size]
        batch_start = time.time()

        try:
            if vectorstore is None:
                # 第一批：创建向量库
                vectorstore = SimpleVectorStore.from_documents(
                    documents=batch,
                    embedding=embedder,
                    persist_path=vs_path,
                )
            else:
                # 后续批次：追加
                vectorstore.add_documents(batch)

            written += len(batch)
            batch_elapsed = time.time() - batch_start

            if pbar:
                pbar.update(len(batch))
                pbar.set_postfix_str(
                    f"批次{batch_no+1}/{num_batches} | {len(batch)/batch_elapsed:.0f}chunk/s"
                )

        except Exception as e:
            print(f"\n  [ERROR] SimpleVS 批次 {batch_no+1} 写入失败: {e}")
            traceback.print_exc()
            if vectorstore is None:
                print("[FATAL] 向量库创建失败，终止入库")
                break
            else:
                print(f"  [跳过] 批次 {batch_no+1}，继续下一批...")
                continue

    if pbar:
        pbar.close()

    # 最终确认持久化
    if vectorstore is not None:
        vectorstore.save()
        print(f"\n[SimpleVS] 完成: 成功写入 {written}/{total} 个 chunk → {vs_path}")

    return vectorstore


# ================================================================
# 7. 主流程
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description="离线法律知识库建库工具 — 6 Phase 工业级流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python build_db.py                             # 完整建库（Phase 1→6）
  python build_db.py --from-cache                # 断点续传（Phase 5→6）
  python build_db.py --workers-load 4 --workers-embed 12
  python build_db.py --batch-size 200            # 更小的 ChromaDB 批次
        """,
    )
    parser.add_argument(
        "--from-cache", action="store_true",
        help="跳过 Phase 1~4（文件加载+切分），直接从 chunks_cache.jsonl 读取并入库"
    )
    parser.add_argument(
        "--workers-load", type=int, default=MAX_WORKERS_LOAD,
        help=f"文件加载并发线程数（默认 {MAX_WORKERS_LOAD}）"
    )
    parser.add_argument(
        "--workers-embed", type=int, default=MAX_WORKERS_EMBED,
        help=f"Embedding API 并发线程数（默认 {MAX_WORKERS_EMBED}）"
    )
    parser.add_argument(
        "--batch-size", type=int, default=CHROMA_BATCH_SIZE,
        help=f"ChromaDB 每批写入 chunk 数（默认 {CHROMA_BATCH_SIZE}，越小越抗 Ctrl+C）"
    )
    parser.add_argument(
        "--data-dir", type=str, default=DATA_DIR,
        help=f"数据目录（默认 {DATA_DIR}）"
    )
    args = parser.parse_args()

    load_workers = args.workers_load
    embed_workers = args.workers_embed
    chroma_batch = args.batch_size

    # ================================================================
    # 欢迎信息
    # ================================================================
    print("=" * 72)
    print("  build_db.py — 离线法律知识库建库工具")
    print(f"  数据目录:    {args.data_dir}")
    print(f"  缓存文件:    {CACHE_FILE}")
    print(f"  向量库路径:  {VECTORSTORE_PATH}")
    print(f"  加载线程:    {load_workers}")
    print(f"  Embed线程:   {embed_workers}")
    print(f"  Chroma批次:  {chroma_batch}")
    print(f"  模式:        {'断点续传' if args.from_cache else '完整建库'}")
    print("=" * 72)

    overall_start = time.time()
    file_list = []

    # ================================================================
    # Phase 1~4: 文件扫描 → 加载 → 切分 → JSONL 缓存
    # ================================================================
    if args.from_cache:
        print("\n" + "=" * 72)
        print("[模式] --from-cache：跳过 Phase 1~4，直接从 JSONL 读取")
        print("=" * 72)
        chunks = load_chunks_from_jsonl(CACHE_FILE)
        if not chunks:
            print("[ERROR] JSONL 缓存为空或损坏，请先完整运行一次建库")
            return
    else:
        # ── Phase 1: 扫描 ──
        print("\n" + "=" * 72)
        print("[Phase 1] 扫描数据目录")
        print("=" * 72)
        file_list = scan_files(args.data_dir)
        print(f"  → 发现 {len(file_list)} 个文件（pdf/docx）")

        if not file_list:
            print("[ERROR] 未发现任何文档文件，请检查 data/ 目录")
            return

        # ── Phase 2: 多线程加载 ──
        print("\n" + "=" * 72)
        print(f"[Phase 2] 多线程文件加载（{load_workers} 线程）")
        print("=" * 72)

        from langchain_core.documents import Document

        all_docs: List[Document] = []
        errors: List[str] = []

        try:
            from tqdm import tqdm
            pbar = tqdm(total=len(file_list), desc="加载文件", unit="file")
        except ImportError:
            pbar = None

        load_start = time.time()
        with ThreadPoolExecutor(max_workers=load_workers) as executor:
            future_map = {}
            for fp, cat in file_list:
                if _interrupted.is_set():
                    break
                future = executor.submit(load_single_file, fp, cat, LOAD_TIMEOUT)
                future_map[future] = (fp, cat)

            for future in as_completed(future_map):
                if _interrupted.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                fp, cat = future_map[future]
                try:
                    docs = future.result(timeout=LOAD_TIMEOUT + 10)
                    all_docs.extend(docs)
                except Exception as e:
                    errors.append(f"{os.path.basename(fp)}: {type(e).__name__}: {e}")
                if pbar:
                    pbar.update(1)

        if pbar:
            pbar.close()

        load_elapsed = time.time() - load_start
        print(f"\n[Phase 2] 完成: {len(all_docs)} 个原始文档, {len(file_list)} 个文件, {load_elapsed:.1f}s")
        if errors:
            print(f"  加载异常 {len(errors)} 个（前 10 个）：")
            for e in errors[:10]:
                safe_e = str(e).encode('gbk', errors='replace').decode('gbk')
                print(f"    - {safe_e}")

        if _interrupted.is_set():
            print("[中断] 用户取消，已加载的数据未持久化（Phase 4 之前）")
            return

        # ── Phase 3: 切分 ──
        print("\n" + "=" * 72)
        print("[Phase 3] LegalRegexSplitter 法律文档切分")
        print("=" * 72)

        split_start = time.time()
        splitter = LegalRegexSplitter()
        chunks = splitter.split_documents(all_docs)
        split_elapsed = time.time() - split_start

        # 统计地域分布
        region_counts: Dict[str, int] = {}
        for ch in chunks:
            r = ch.metadata.get("region", "未知")
            region_counts[r] = region_counts.get(r, 0) + 1

        print(f"  → {len(chunks)} 个 chunk（耗时 {split_elapsed:.1f}s）")
        print(f"  → 地域分布 Top 10：")
        for region, cnt in sorted(region_counts.items(), key=lambda x: -x[1])[:10]:
            bar = "█" * max(1, int(40 * cnt / max(region_counts.values())))
            print(f"      {region:<8} {cnt:>6}  {bar}")

        if _interrupted.is_set():
            print("[中断] 用户取消")
            return

        # ── Phase 4: JSONL 缓存 ──
        print("\n" + "=" * 72)
        print("[Phase 4] 写入 JSONL 缓存（断点续传）")
        print("=" * 72)
        save_chunks_to_jsonl(chunks, CACHE_FILE)

    # ================================================================
    # Phase 5: 并发 Embedding → 分批写入 SimpleVectorStore
    # ================================================================
    print("\n" + "=" * 72)
    print(f"[Phase 5] 并发 Embedding + 分批写入 SimpleVectorStore（{embed_workers} 线程）")
    print("=" * 72)

    embedder = ConcurrentDashScopeEmbeddings(
        api_key=API_KEY,
        base_url=BASE_URL,
        model=EMBED_MODEL,
        max_workers=embed_workers,
    )

    vectorstore = write_to_simple_vs(
        chunks, embedder, VECTORSTORE_PATH, chroma_batch
    )

    if _interrupted.is_set():
        print("\n[中断] Ctrl+C 触发，已入库数据安全落盘 ✅")
        # 不 return，继续展示已完成部分的统计

    # ================================================================
    # Phase 6: 验证入库结果
    # ================================================================
    print("\n" + "=" * 72)
    print("[Phase 6] 验证入库结果")
    print("=" * 72)

    try:
        from simple_vectorstore import SimpleVectorStore

        class _VerifyEmbeddings(Embeddings):
            def embed_documents(self, texts):
                return embedder.embed_documents(texts, show_progress=False)
            def embed_query(self, text):
                return embedder.embed_query(text)

        if os.path.exists(VECTORSTORE_PATH):
            verify_store = SimpleVectorStore(
                persist_path=VECTORSTORE_PATH,
                embedding_function=_VerifyEmbeddings(),
            )
            verify_store.load()
            final_count = verify_store.count()
        else:
            final_count = 0
    except Exception as e:
        print(f"[WARN] 验证失败: {e}")
        traceback.print_exc()
        final_count = 0

    overall_elapsed = time.time() - overall_start

    # ================================================================
    # 最终报告
    # ================================================================
    print()
    print("=" * 72)
    print("                        建 库 完 成")
    print("=" * 72)
    print(f"  文 件 数 : {len(file_list) if file_list else '(从缓存恢复)'}")
    print(f"  Chunk 数 : {len(chunks)}")
    print(f"  入库条数 : {final_count}")
    print(f"  总 耗 时 : {overall_elapsed:.1f}s ({overall_elapsed/60:.1f}min)")
    print(f"  向量库路径: {VECTORSTORE_PATH}")
    print(f"  JSONL缓存: {CACHE_FILE}")
    print("=" * 72)

    if final_count > 0 and final_count != len(chunks):
        print(f"\n⚠️  警告：入库 {final_count} ≠ chunk 数 {len(chunks)}，"
              f"差异 {abs(final_count - len(chunks))} 条，请排查")
    elif final_count == 0:
        print("\n⚠️  警告：入库条数为 0，可能是 API 连接异常")
    else:
        print(f"\n✅ 入库条数与 chunk 数一致 ({final_count})，建库成功！")


if __name__ == "__main__":
    main()
