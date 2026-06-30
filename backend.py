#!/usr/bin/env python3
"""
劳动法律师智能助理 
特色：无损记忆压缩防失忆、前台 AI 动态读取右侧卷宗防重复提问、思维链推理

API 配置说明：
  - 不再依赖 .env 或硬编码 Key
  - 每个用户注册时绑定自己的 API Key / Base URL / Model
  - 支持多种 OpenAI 兼容接口：Qwen(DashScope)、DeepSeek、SiliconFlow 等
  - 调用 init_backend(api_config) 按用户配置初始化后端
"""

import os
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

import json
import re
import sys
from typing import TypedDict, List, Dict, Annotated

# ── PyInstaller 打包路径兼容 ──
if getattr(sys, 'frozen', False):
    _BASE_DIR = sys._MEIPASS
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from langchain_openai import ChatOpenAI
from langchain.embeddings.base import Embeddings
from simple_vectorstore import SimpleVectorStore
from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredWordDocumentLoader
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, RemoveMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

# ==========================================
# 1. 自定义兼容多平台的 Embeddings
# ==========================================
class DashScopeEmbeddings(Embeddings):
    """兼容 OpenAI 格式的 Embeddings（支持 Qwen / DeepSeek / 硅基流动 等）"""
    def __init__(self, api_key: str, base_url: str, model: str = "text-embedding-v2"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        import requests
        _verify_ssl = os.environ.get("VERIFY_SSL", "true").lower() != "false"
        embeddings = []
        for text in texts:
            response = requests.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "input": text,
                    "encoding_format": "float"
                },
                verify=_verify_ssl
            )
            if response.status_code == 200:
                result = response.json()
                if "data" in result and len(result["data"]) > 0:
                    embeddings.append(result["data"][0]["embedding"])
                else:
                    embeddings.append([0.0] * 1536)
            else:
                embeddings.append([0.0] * 1536)
        return embeddings
    
    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

# ==========================================
# 2. API Provider 预设配置
# ==========================================
# 主流平台默认 Base URL，用户也可以自定义
API_PROVIDER_PRESETS = {
    "qwen": {
        "name": "阿里云百炼 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "embedding_model": "text-embedding-v2",
    },
    "deepseek": {
        "name": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "embedding_model": "text-embedding-v2",  # DeepSeek 无 embedding，需用户另行配置
    },
    "siliconflow": {
        "name": "硅基流动 (SiliconFlow)",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
        "embedding_model": "BAAI/bge-large-zh-v1.5",
    },
    "custom": {
        "name": "自定义 OpenAI 兼容接口",
        "base_url": "",
        "default_model": "",
        "embedding_model": "text-embedding-v2",
    },
}

# ==========================================
# 3. 后端模块级变量（由 init_backend() 按用户配置初始化）
# ==========================================
llm = None
llm_fast = None
embeddings = None
app = None
vectorstore = None
retriever = None
graph_store = None
hybrid_retriever = None

_SCRIPT_DIR = _BASE_DIR
VECTORSTORE_PATH = os.path.join(_SCRIPT_DIR, "vectorstore.pkl")
GRAPH_DB_PATH = os.path.join(_SCRIPT_DIR, "legal_graph.db")


def _mask_key(key: str) -> str:
    """脱敏打印 API Key"""
    if not key:
        return "(未设置)"
    if len(key) <= 12:
        return key[:4] + "****"
    return key[:8] + "..." + key[-4:]


def init_backend(api_config: dict) -> bool:
    """
    根据用户 API 配置初始化后端引擎。
    
    api_config 应包含:
        - api_key:      用户的 API Key（必填）
        - api_provider: 平台标识 "qwen" / "deepseek" / "siliconflow" / "custom"
        - base_url:     API 端点地址（可选，留空则按 provider 自动匹配）
        - model:        模型名称（可选，留空则按 provider 自动匹配）
    
    返回 True 表示初始化成功。
    """
    global llm, llm_fast, embeddings, app, vectorstore
    
    api_key = (api_config.get("api_key") or "").strip()
    provider = (api_config.get("api_provider") or "qwen").strip()
    base_url = (api_config.get("base_url") or "").strip()
    model = (api_config.get("model") or "").strip()
    
    if not api_key:
        print(">>> [后端] 未提供 API Key，无法初始化")
        return False
    
    # 根据 provider 补充默认值
    preset = API_PROVIDER_PRESETS.get(provider, API_PROVIDER_PRESETS["custom"])
    if not base_url:
        base_url = preset["base_url"]
    if not model:
        model = preset["default_model"]
    embedding_model = preset.get("embedding_model", "text-embedding-v2")
    
    print(f">>> 正在按用户配置初始化后端...")
    print(f">>> 平台: {preset['name']}")
    print(f">>> API Key: {_mask_key(api_key)}")
    print(f">>> Base URL: {base_url}")
    print(f">>> 模型: {model}")
    
    # 测试 API 连接
    try:
        import requests as _req
        _test_resp = _req.get(
            base_url.replace("/compatible-mode/v1", "").replace("/v1", ""),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
            verify=False
        )
        print(f">>> API 端点连通性测试: HTTP {_test_resp.status_code}")
    except Exception as _e:
        print(f">>> ⚠️ API 端点连通性测试失败: {type(_e).__name__}: {_e}")
    
    # 初始化 Embeddings
    embeddings = DashScopeEmbeddings(api_key=api_key, base_url=base_url, model=embedding_model)
    
    # 初始化主 LLM
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        max_tokens=4000
    )
    
    # 轻量级 LLM（用于 triage、query rewrite、质检等场景）
    llm_fast = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
        max_tokens=3000
    )
    
    # 初始化 RAG 知识库
    _init_vectorstore()
    
    # 构建 LangGraph 工作流
    _init_langgraph_app()
    
    print(f">>> 后端初始化完成")
    return True


# ==========================================
# 4. RAG 知识库 (SimpleVectorStore pickle 持久化)
# ==========================================

def load_documents_by_category(data_dir):
    """遍历data目录下所有子目录，加载所有支持的文档"""
    import glob
    import sys
    
    all_documents = []
    
    # 支持的文件格式
    extensions = ["*.pdf", "*.doc", "*.docx"]
    
    # 映射目录名到分类名称
    category_mapping = {
        "法律": "National Laws",
        "地方法律 法规规章": "Local Regulations",
        "行政法规": "Administrative Regulations",
        "规章及法律规范": "Rules and Norms",
    }
    
    # 检查data_dir是否存在
    if not os.path.exists(data_dir):
        print(f"[警告] 数据目录不存在: {data_dir}")
        return all_documents
    
    print(f"\n[INFO] 开始扫描目录: {data_dir}")
    
    # 首先加载data目录下的所有直接文件
    for ext in extensions:
        pattern = os.path.join(data_dir, ext)
        files = glob.glob(pattern)
        for file_path in files:
            print(f"[扫描] 发现文件: {file_path}")
            docs = load_single_file(file_path, "General Documents")
            all_documents.extend(docs)
    
    # 遍历data_dir下的所有子目录
    for subdir in os.listdir(data_dir):
        subdir_path = os.path.join(data_dir, subdir)
        
        # 跳过非目录项
        if not os.path.isdir(subdir_path):
            continue
        
        # 确定分类名称
        category_name = category_mapping.get(subdir, subdir)
        print(f"\n[INFO] 处理目录: {subdir} -> 分类: {category_name}")
        
        # 递归加载该子目录下的所有文件
        for ext in extensions:
            pattern = os.path.join(subdir_path, "**", ext)
            files = glob.glob(pattern, recursive=True)
            
            print(f"  [扫描] {ext} 模式匹配到 {len(files)} 个文件")
            
            for file_path in files:
                try:
                    docs = load_single_file(file_path, category_name)
                    all_documents.extend(docs)
                except Exception as e:
                    print(f"  [错误] 加载失败 {file_path}: {e}")
    
    print(f"\n[完成] 共加载 {len(all_documents)} 个文档")
    return all_documents

def load_single_file(file_path, category, timeout=60):
    """加载单个文件并返回文档列表（支持PDF、DOC、DOCX），超时60秒自动跳过"""
    from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredWordDocumentLoader
    from langchain_core.documents import Document
    import threading
    import queue
    
    docs = []
    file_name = os.path.basename(file_path)
    result_queue = queue.Queue()
    
    def load_with_timeout():
        """在子线程中执行加载操作"""
        try:
            if file_path.endswith('.pdf'):
                loader = PyMuPDFLoader(file_path)
                file_type = "PDF"
            elif file_path.endswith('.docx'):
                loader = UnstructuredWordDocumentLoader(file_path)
                file_type = "DOCX"
            elif file_path.endswith('.doc'):
                loader = UnstructuredWordDocumentLoader(file_path)
                file_type = "DOC"
                print(f"[LibreOffice] 正在转换: {file_name}")
            else:
                result_queue.put(("skip", [], None))
                return
            
            loaded_docs = loader.load()
            for doc in loaded_docs:
                doc.metadata["category"] = category
                doc.metadata["file_type"] = os.path.splitext(file_path)[1]
            result_queue.put(("success", loaded_docs, file_type))
        except UnicodeDecodeError as e:
            result_queue.put(("unicode_error", [], str(e)))
        except Exception as e:
            result_queue.put(("error", [], str(e)))
    
    # 启动加载线程
    load_thread = threading.Thread(target=load_with_timeout, daemon=True)
    load_thread.start()
    
    # 等待结果或超时
    load_thread.join(timeout=timeout)
    
    if load_thread.is_alive():
        # 超时，终止线程
        print(f"[超时跳过] {file_name}: 处理超过{timeout}秒")
        return docs
    
    # 获取结果
    try:
        status, loaded_docs, file_type = result_queue.get_nowait()
        
        if status == "success":
            docs.extend(loaded_docs)
            print(f"[成功] {file_type}: {file_name} ({len(loaded_docs)} 页)")
            return docs
        elif status == "unicode_error" or status == "error":
            err_msg = loaded_docs[0] if loaded_docs else "未知错误"
            print(f"[尝试备用方案] {file_name}: {err_msg}")
        else:
            return docs
    except queue.Empty:
        return docs
    
    # 备用方案：使用 docx2txt 或直接读取二进制
    if file_path.endswith('.doc'):
        # 方案1: 尝试用 docx2txt
        try:
            import docx2txt
            
            def load_docx2txt():
                try:
                    text = docx2txt.process(file_path)
                    result_queue.put(("docx2txt_success", text, None))
                except Exception as e:
                    result_queue.put(("docx2txt_error", str(e), None))
            
            t = threading.Thread(target=load_docx2txt, daemon=True)
            t.start()
            t.join(timeout=timeout)
            
            if t.is_alive():
                print(f"[超时跳过] {file_name}: docx2txt处理超过{timeout}秒")
            else:
                try:
                    status, text, _ = result_queue.get_nowait()
                    if status == "docx2txt_success" and text and len(text.strip()) > 10:
                        doc = Document(
                            page_content=text,
                            metadata={"category": category, "file_type": ".doc", "source": file_path}
                        )
                        docs.append(doc)
                        print(f"[备用方案] {file_name}: 使用docx2txt成功 ({len(text)} 字符)")
                        return docs
                except queue.Empty:
                    pass
        except:
            pass
        
        # 方案2: 使用 subprocess 调用 soffice 直接转换
        try:
            import subprocess
            import tempfile
            import shutil
            
            temp_dir = tempfile.mkdtemp()
            temp_input = os.path.join(temp_dir, "input.doc")
            shutil.copy(file_path, temp_input)
            
            soffice_cmd = "soffice"  # 依赖系统 PATH 中的 LibreOffice
            result = subprocess.run([
                soffice_cmd, "--headless", "--convert-to", "txt:Text",
                "--outdir", temp_dir, temp_input
            ], capture_output=True, timeout=timeout)
            
            output_file = os.path.join(temp_dir, "input.txt")
            if os.path.exists(output_file):
                with open(output_file, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                if text and len(text.strip()) > 10:
                    doc = Document(
                        page_content=text,
                        metadata={"category": category, "file_type": ".doc", "source": file_path}
                    )
                    docs.append(doc)
                    print(f"[备用方案] {file_name}: 使用soffice直接转换成功 ({len(text)} 字符)")
            
            shutil.rmtree(temp_dir, ignore_errors=True)
            return docs
        except subprocess.TimeoutExpired:
            print(f"[超时跳过] {file_name}: soffice转换超过{timeout}秒")
        except Exception as e2:
            print(f"[备用方案失败] {file_name}: {e2}")
    
    return docs


def scan_data_directory(data_dir="./data/"):
    """扫描data目录，返回目录结构和文件统计信息（供Streamlit前端显示）"""
    import glob
    import time
    
    result = {
        "success": True,
        "message": "",
        "start_time": time.time(),
        "directories": [],
        "total_files": 0,
        "file_breakdown": {
            "pdf": 0,
            "doc": 0,
            "docx": 0
        }
    }
    
    if not os.path.exists(data_dir):
        result["success"] = False
        result["message"] = f"数据目录不存在: {data_dir}"
        return result
    
    # 目录映射
    category_mapping = {
        "法律": "National Laws",
        "地方法律 法规规章": "Local Regulations",
        "行政法规": "Administrative Regulations",
        "规章及法律规范": "Rules and Norms",
    }
    
    extensions = ["*.pdf", "*.doc", "*.docx"]
    
    # 扫描data目录下的直接文件
    for ext in extensions:
        pattern = os.path.join(data_dir, ext)
        files = glob.glob(pattern)
        if files:
            ext_name = ext.replace("*.", "")
            result["file_breakdown"][ext_name] += len(files)
            result["total_files"] += len(files)
            result["directories"].append({
                "name": "根目录文件",
                "category": "General Documents",
                "files": files,
                "count": len(files)
            })
    
    # 遍历子目录
    for subdir in os.listdir(data_dir):
        subdir_path = os.path.join(data_dir, subdir)
        
        if not os.path.isdir(subdir_path):
            continue
        
        category = category_mapping.get(subdir, subdir)
        dir_info = {
            "name": subdir,
            "category": category,
            "files": [],
            "count": 0,
            "file_types": {"pdf": 0, "doc": 0, "docx": 0}
        }
        
        for ext in extensions:
            pattern = os.path.join(subdir_path, "**", ext)
            files = glob.glob(pattern, recursive=True)
            ext_name = ext.replace("*.", "")
            dir_info["files"].extend(files)
            dir_info["file_types"][ext_name] = len(files)
            dir_info["count"] += len(files)
            result["file_breakdown"][ext_name] += len(files)
            result["total_files"] += len(files)
        
        result["directories"].append(dir_info)
    
    result["end_time"] = time.time()
    result["elapsed"] = result["end_time"] - result["start_time"]
    
    return result


def rebuild_vectorstore_with_progress(data_dir="./data/", persist_dir="./chroma_db_pro/", 
                                        progress_callback=None):
    """重建向量数据库，支持进度回调（供Streamlit前端显示）"""
    import glob
    import time
    from simple_vectorstore import SimpleVectorStore
    
    start_time = time.time()
    
    result = {
        "success": True,
        "message": "",
        "start_time": start_time,
        "documents_loaded": 0,
        "chunks_created": 0,
        "files_processed": 0,
        "errors": [],
        "directory_stats": []
    }
    
    if progress_callback:
        progress_callback({
            "status": "scanning",
            "message": "正在扫描数据目录...",
            "progress": 0
        })
    
    # 扫描目录
    scan_result = scan_data_directory(data_dir)
    if not scan_result["success"]:
        result["success"] = False
        result["message"] = scan_result["message"]
        return result
    
    result["directory_stats"] = scan_result["directories"]
    total_files = scan_result["total_files"]
    
    if progress_callback:
        progress_callback({
            "status": "scanning",
            "message": f"扫描完成，发现 {total_files} 个文件",
            "progress": 5,
            "details": scan_result
        })
    
    if total_files == 0:
        result["success"] = False
        result["message"] = "未发现任何文档文件"
        return result
    
    # 加载所有文档
    all_documents = []
    category_mapping = {
        "法律": "National Laws",
        "地方法律 法规规章": "Local Regulations",
        "行政法规": "Administrative Regulations",
        "规章及法律规范": "Rules and Norms",
    }
    
    processed_files = 0
    errors = []
    
    # 遍历所有目录和文件
    for dir_info in scan_result["directories"]:
        dir_name = dir_info["name"]
        category = dir_info["category"]
        files = dir_info["files"]
        
        if progress_callback:
            progress_callback({
                "status": "loading",
                "message": f"正在加载 {dir_name}...",
                "progress": 5 + int(45 * processed_files / max(total_files, 1)),
                "current_dir": dir_name,
                "files_done": processed_files,
                "files_total": total_files
            })
        
        for file_path in files:
            try:
                docs = load_single_file(file_path, category)
                all_documents.extend(docs)
                processed_files += 1
                
                # 每处理10个文件报告一次进度
                if processed_files % 10 == 0 and progress_callback:
                    progress_callback({
                        "status": "loading",
                        "message": f"已加载 {processed_files}/{total_files} 个文件",
                        "progress": 5 + int(45 * processed_files / max(total_files, 1)),
                        "files_done": processed_files,
                        "files_total": total_files
                    })
            except Exception as e:
                errors.append(f"{file_path}: {str(e)}")
    
    result["documents_loaded"] = len(all_documents)
    result["files_processed"] = processed_files
    result["errors"] = errors[:50]  # 只保留前50个错误
    
    if progress_callback:
        progress_callback({
            "status": "splitting",
            "message": f"加载完成，共 {len(all_documents)} 个文档，正在切分...",
            "progress": 50
        })
    
    # 切分文档
    if all_documents:
        splitter = LegalRegexSplitter()
        splits = splitter.split_documents(all_documents)
        result["chunks_created"] = len(splits)
        
        if progress_callback:
            progress_callback({
                "status": "splitting",
                "message": f"切分完成，共 {len(splits)} 个切块，正在写入向量数据库...",
                "progress": 70
            })
        
        # 创建/清空向量数据库
        import shutil
        if os.path.exists(persist_dir):
            if progress_callback:
                progress_callback({
                    "status": "clearing",
                    "message": "正在清空旧数据库...",
                    "progress": 75
                })
            try:
                shutil.rmtree(persist_dir)
            except Exception as e:
                errors.append(f"清空旧数据库失败: {str(e)}")
        
        if progress_callback:
            progress_callback({
                "status": "saving",
                "message": "正在写入向量数据...",
                "progress": 80
            })
        
        # 写入新数据
        vectorstore = Chroma.from_documents(
            documents=splits, 
            embedding=embeddings, 
            persist_directory=persist_dir
        )
        
        if progress_callback:
            progress_callback({
                "status": "saving",
                "message": "向量数据写入完成，正在验证...",
                "progress": 95
            })
        
        # 验证
        verify_store = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
        verify_data = verify_store.get()
        result["final_chunks"] = len(verify_data.get('ids', []))
    
    end_time = time.time()
    result["end_time"] = end_time
    result["total_time"] = end_time - start_time
    result["success"] = True
    result["message"] = f"完成！总耗时 {result['total_time']:.1f} 秒"
    
    if progress_callback:
        progress_callback({
            "status": "complete",
            "message": result["message"],
            "progress": 100,
            "summary": result
        })
    
    return result

class LegalRegexSplitter:
    """专为中国法律文档定制的正则切分器"""
    def split_documents(self, documents):
        import re
        import os
        from langchain_core.documents import Document
        
        fallback_splitter = None
        try:
            from langchain.text_splitter import RecursiveCharacterTextSplitter 
            fallback_splitter = RecursiveCharacterTextSplitter(
                chunk_size=500,
                chunk_overlap=50,
                separators=["\n\n", "\n", "。", "；"]
            )
        except ImportError:
            pass
        
        source_text_map = {}
        for doc in documents:
            source = doc.metadata.get("source", "未知法律文件")
            category = doc.metadata.get("category", "未分类")
            if source not in source_text_map:
                source_text_map[source] = {"text": "", "category": category}
            source_text_map[source]["text"] += doc.page_content + "\n\n"

        final_chunks = []
        for source, data in source_text_map.items():
            text = data["text"]
            category = data["category"]
            
            # === 新增：地域标签识别 ===
            ext = os.path.splitext(source)[1]
            law_name = os.path.basename(source).replace(ext, "")
            regions = ["北京", "上海", "天津", "重庆", "广东", "江苏", "浙江", "山东", "河南", "四川", "湖北", "湖南", "河北", "安徽", "辽宁", "福建", "陕西", "江西", "黑龙江", "广西", "云南", "贵州", "山西", "吉林", "内蒙古", "新疆", "甘肃", "海南", "宁夏", "青海", "西藏", "深圳", "广州"]
            doc_region = "全国" # 默认全局生效
            for r in regions:
                if r in law_name:
                    doc_region = r
                    break
            # =========================

            chunks_before_this_file = len(final_chunks)
            
            text = re.sub(r'(?<=[^。；：？！\n])\n(?![（\(][一二三四五六七八九十]+[）\)]|\d+\.)', '', text)
            
            lines = text.split('\n')
            current_chapter = ""
            current_section = ""
            
            chapter_pattern = re.compile(r'^第[一二三四五六七八九十百]+章\s+(.*)')
            section_pattern = re.compile(r'^第[一二三四五六七八九十百]+节\s+(.*)')
            article_pattern = re.compile(r'^(第[一二三四五六七八九十百千万]+条[\s、，。])(.*)')
            
            current_article_text = ""
            
            def save_current_article():
                nonlocal current_article_text
                if len(current_article_text.strip()) > 10:
                    hierarchy = f"《{law_name}》"
                    if current_chapter: hierarchy += f" [{current_chapter}]"
                    if current_section: hierarchy += f" [{current_section}]"
                    
                    enhanced_content = f"{hierarchy}\n{current_article_text.strip()}"
                    final_chunks.append(Document(
                        page_content=enhanced_content, 
                        # 👇 注意这里：已经把 "region": doc_region 加进去了
                        metadata={"source": source, "law_name": law_name, "category": category, "chapter": current_chapter, "region": doc_region}
                    ))
                current_article_text = ""

            for line in lines:
                line = line.strip()
                if not line: continue
                
                if chapter_pattern.match(line):
                    current_chapter = line; current_section = ""; continue
                if section_pattern.match(line):
                    current_section = line; continue
                    
                article_match = article_pattern.match(line)
                if article_match:
                    save_current_article()
                    current_article_text = line 
                else:
                    if current_article_text:
                        current_article_text += f"\n{line}"
            
            save_current_article()

            if len(final_chunks) == chunks_before_this_file:
                # No article pattern found - use simple chunking
                if fallback_splitter:
                    fallback_docs = fallback_splitter.create_documents(
                        [text], 
                        metadatas=[{"source": source, "law_name": law_name, "category": category, "chapter": "SimpleChunk", "region": doc_region}]
                    )
                    for fb_doc in fallback_docs:
                        fb_doc.page_content = f"《{law_name}》\n{fb_doc.page_content}"
                        final_chunks.append(fb_doc)
                else:
                    # Fallback if no splitter available - just split by paragraphs
                    paragraphs = text.split('\n\n')
                    for para in paragraphs:
                        if len(para.strip()) > 10:
                            final_chunks.append(Document(
                                page_content=f"《{law_name}》\n{para.strip()}",
                                metadata={"source": source, "law_name": law_name, "category": category, "chapter": "SimpleChunk", "region": doc_region}
                            ))

        return final_chunks

def _init_vectorstore():
    """初始化/加载 RAG 向量知识库"""
    global vectorstore, retriever, embeddings, graph_store, hybrid_retriever
    
    vectorstore = SimpleVectorStore(persist_path=VECTORSTORE_PATH, embedding_function=embeddings)
    if os.path.exists(VECTORSTORE_PATH):
        print(">>> 发现已存在的向量知识库，正在加载...")
        vectorstore.load()
        print(f">>> 加载完成: {vectorstore.count()} 条向量")
    else:
        print(">>> 启动法条切分引擎，正在构建知识库...")
        data_dir = os.path.join(_SCRIPT_DIR, 'data', '')
        os.makedirs(data_dir, exist_ok=True)
        
        # 分门别类加载文档
        documents = load_documents_by_category(data_dir)
        
        if documents:
            print(f"\n[成功] 共加载 {len(documents)} 个文档，正在切分入库...")
            splitter = LegalRegexSplitter()
            splits = splitter.split_documents(documents)
            print(f"[成功] 完美切分出 {len(splits)} 条独立的法律条款！正在入库...")
            vectorstore = SimpleVectorStore.from_documents(
                documents=splits, embedding=embeddings, persist_path=VECTORSTORE_PATH
            )
        else:
            print("[警告] ./data/ 目录下没有文档，请放入法律文件后重启。")
            # 创建空向量库
            vectorstore = SimpleVectorStore(persist_path=VECTORSTORE_PATH, embedding_function=embeddings)

    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    # GraphRAG 是可选增强：数据库存在则启用，不存在仍保持原向量检索。
    graph_store = None
    hybrid_retriever = None
    if os.path.exists(GRAPH_DB_PATH):
        try:
            from graph_store import LegalGraphStore
            from hybrid_retriever import HybridLegalRetriever

            graph_store = LegalGraphStore(GRAPH_DB_PATH, read_only=True)
            hybrid_retriever = HybridLegalRetriever(vectorstore, graph_store)
            entity_count, rule_count, source_count = graph_store.counts()
            print(
                f">>> GraphRAG 已启用: {entity_count} 实体 / "
                f"{rule_count} 规则 / {source_count} 来源"
            )
        except Exception as exc:
            graph_store = None
            hybrid_retriever = None
            print(f">>> [WARN] GraphRAG 初始化失败，回退向量检索: {exc}")

# ==========================================
# 4. 定义全局状态 (新增并行与自我纠错字段)
# ==========================================
class LaborLawState(TypedDict):
    messages: Annotated[list, add_messages] 
    chat_summary: str                       
    
    triage_result: dict                     
    form_data: dict                         
    legal_facts_summary: str
    
    # 🌟 优化二新增：并行子图的各自产出
    relevant_laws: str
    similar_cases: str
    
    # 🌟 优化一新增：审查与纠错机制字段
    final_review: str
    reviewer_feedback: str # 质检员的打回修改意见
    retry_count: int       # 重试计数器，防止死循环
    is_pass_flag: bool     # 是否通过质检

    # 🌟 RAG 溯源归因：存储检索到的原始文档 metadata（source / article / text）
    relevant_sources: list

# ==========================================
# 5. 定义智能体节点函数
# ==========================================

from typing import Literal

class TriageOutput(BaseModel):
    """分诊台结构化输出模型"""
    model_config = {"use_enum_values": True}
    action: Literal["chat", "form"] = Field(description="动作类型：只能是 'chat' 或者是 'form'")
    category: str = Field(description="意图分类")
    reply: str = Field(description="回复给用户的话术")

class SearchQueries(BaseModel):
    """查询重写结构化输出模型"""
    queries: List[str] = Field(description="包含3个核心法律检索短语的数组")

# 🌟 新增：质检员结构化输出
class QualityOutput(BaseModel):
    """质检员输出模型"""
    is_pass: bool = Field(description="审查是否合格。若有明显漏洞则为False")
    feedback: str = Field(description="如果不合格，指出具体修改意见。如果合格，填'无'")

def summarize_conversation_node(state: LaborLawState):
    """节点0：Context 工程记忆压缩机（每10轮对话压缩一次）"""
    messages = state.get("messages", [])
    old_summary = state.get("chat_summary", "")
    
    if len(messages) <= 10:
        return {}
        
    print(f"\n[CONTEXT] 检测到对话达到 {len(messages)} 条，触发第 {len(messages)//10} 次 Context 压缩...")
    # 保留最近4条（2轮完整对话），压缩更早的内容
    messages_to_summarize = messages[:-4]
    
    # 获取当前卷宗状态，指导压缩时重点保留
    form_data = state.get("form_data", {})
    if not form_data:
        form_data = {"案件发生地": "", "单位名称": "", "平均月薪": "", "时间节点": "", "核心诉求": "", "详细经过": ""}
    
    missing_fields = [k for k, v in form_data.items() if not v]
    filled_fields = [f"{k}: {v}" for k, v in form_data.items() if v]
    missing_hint = f"目前仍缺失的字段：{missing_fields}" if missing_fields else "所有字段已收集完毕"
    filled_hint = f"已收集到的字段：{'; '.join(filled_fields)}" if filled_fields else "暂无已收集字段"
    
    prompt = f"""你是一名极其严谨的法庭书记员，正在进行 Context 工程压缩。

⚠️ 压缩核心目标：在大幅缩减对话长度的同时，绝对保留所有对填写右侧卷宗有用的信息！

【当前右侧卷宗状态】：
{filled_hint}
{missing_hint}

⚠️ 绝对禁止省略以下关键信息（如果出现过）：
1. 具体的数字（工资数额、索赔金额、工作年限、赔偿金额等）
2. 具体的时间节点（哪年哪月入职/离职/发生争议，几号）
3. 具体的地点（城市、省份）
4. 公司/单位的具体名称和行为
5. 用户的核心诉求和情绪
6. 任何与缺失字段「{missing_fields}」相关的线索

⚠️ 可以安全省略的内容：
- 问候、寒暄、客套话
- AI 的重复解释和安抚
- 已在卷宗中明确记录的信息（但保留细节补充）

【核心限制】：请用精准的要点（Bullet Points）罗列关键事实。合并后的总字数必须严格控制在 600 字以内！

【已有案件档案】：
{old_summary if old_summary else "暂无"}

【待压缩的早期对话】：
{messages_to_summarize}

请直接输出更新后的完整档案文本。"""
    
    response = llm.invoke([HumanMessage(content=prompt)])
    new_summary = response.content
    delete_messages = [RemoveMessage(id=m.id) for m in messages_to_summarize]
    
    return {
        "chat_summary": new_summary,
        "messages": delete_messages 
    }





def triage_node(state: LaborLawState) -> LaborLawState:
    """节点1：前台分诊 + Context 工程信息完善度审视"""
    print("\n[AI] [分诊台 AI] 正在结合右侧卷宗与聊天记录分析意图...")
    chat_history = state.get("messages", [])
    summary = state.get("chat_summary", "")
    summary_text = f"\n【⚠️ 长期背景案件档案（压缩后的历史记忆）】：\n{summary}" if summary else ""
    
    form_data = state.get("form_data", {})
    if not form_data: 
        form_data = {"案件发生地": "", "单位名称": "", "平均月薪": "", "时间节点": "", "核心诉求": "", "详细经过": ""}
        
    # 信息完善度分析
    filled = {k: v for k, v in form_data.items() if v}
    missing = [k for k, v in form_data.items() if not v]
    total_fields = len(form_data)
    filled_count = len(filled)
    completeness_pct = int(filled_count / total_fields * 100) if total_fields > 0 else 0
    
    form_status = "\n".join([
        f"- {k}: ✅ {v}" if v else f"- {k}: ❌ [缺失，待补充]"
        for k, v in form_data.items()
    ])
    
    # 判断是否刚经历过压缩（summary 非空且对话很短说明刚压缩完）
    is_post_compression = bool(summary) and len(chat_history) <= 6
    
    compression_note = ""
    if is_post_compression:
        compression_note = f"""
【🔔 Context 压缩后审视指令（重要！）】：
刚刚完成了对话记忆压缩。请你现在做两件事：
1. 仔细审视右侧卷宗中每个字段的状态，检查是否有信息遗漏或矛盾
2. 根据缺失字段，规划下一个最关键的问题来完善信息
3. 如果核心信息（至少有：案件发生地、核心诉求、详细经过）已齐全，请立即转交表单
"""
    
    # 核心信息判断：至少3个关键字段已填写
    core_fields = ["核心诉求", "详细经过"]
    core_filled = sum(1 for f in core_fields if form_data.get(f, ""))
    has_basic_info = filled_count >= 3 and core_filled >= 1
    
    # 精简版状态提示，省去不必要的长句子
    prompt = f"""你是一名劳动法律师助理。任务：根据【卷宗】判断并回复。

【当前卷宗】：
{form_status}
{summary_text}
完善度: {completeness_pct}%。{'可转交报告' if has_basic_info else '需继续追问'}
{compression_note}

【核心指令】：
1. 绝不重复询问已填字段。每次只自然追问1个核心缺失字段。
2. 若完善度≥60%且含核心诉求/经过，或用户要求出报告，设action="form"，否则为"chat"。

【严格输出格式】
必须先输出极简思考(省token)，再输出JSON：
<thinking>用一句话简述缺什么、该问什么或是否结束收集（50字内）</thinking>
<output>
{{
    "action": "chat" 或 "form",
    "category": "案件分类",
    "reply": "直接发给用户的自然语言回复，不要有任何废话"
}}
</output>"""
    messages_for_llm = [SystemMessage(content=prompt)]
    # 只传 HumanMessage，避免旧 AIMessage 中的 thinking 标签污染 LLM 上下文
    for msg in chat_history:
        if isinstance(msg, HumanMessage):
            messages_for_llm.append(msg)
        elif isinstance(msg, AIMessage):
            # AIMessage 只传纯文本内容（去掉 thinking 标签），避免上下文污染
            clean = msg.content
            if "<thinking>" in clean and "</thinking>" in clean:
                clean = re.sub(r'<thinking>.*?</thinking>', '', clean, flags=re.DOTALL).strip()
            if clean:
                messages_for_llm.append(AIMessage(content=clean))
    
    # ── 原生 LLM 调用 + 手动正则解析 ──
    last_error = ""
    try:
        raw_output = llm_fast.invoke(messages_for_llm).content
        print(f"[TRIAGE] LLM 原始输出: {raw_output[:500]}...")
    except Exception as e:
        last_error = f"LLM调用失败: {type(e).__name__}: {e}"
        print(f"[ERROR] 分诊台 {last_error}")
        # 重试一次用 llm
        try:
            raw_output = llm.invoke(messages_for_llm).content
            print(f"[TRIAGE] 重试成功: {raw_output[:300]}...")
            last_error = ""
        except Exception as e2:
            last_error = f"LLM重试也失败: {type(e2).__name__}: {e2}"
            print(f"[ERROR] 分诊台 {last_error}")
            raw_output = ""
    
    # 提取 <thinking> 和 <output>
    thinking_text = ""
    output_text = ""
    
    if raw_output:
        think_match = re.search(r'<thinking>(.*?)</thinking>', raw_output, re.DOTALL)
        if think_match:
            thinking_text = think_match.group(1).strip()
        
        out_match = re.search(r'<output>(.*?)</output>', raw_output, re.DOTALL)
        if out_match:
            output_text = out_match.group(1).strip()
        else:
            # 没有 <output> 标签，尝试把 </thinking> 之后的内容当 output
            after_think = re.search(r'</thinking>(.*)', raw_output, re.DOTALL)
            if after_think:
                output_text = after_think.group(1).strip()
            else:
                # 完全没有标签结构，把整个输出当 output
                output_text = raw_output.strip()
    
    # 解析 JSON
    triage_result = None
    if output_text:
        # 清理 markdown 代码块包裹
        json_str = re.sub(r'^```(?:json)?\s*', '', output_text)
        json_str = re.sub(r'\s*```$', '', json_str)
        json_str = json_str.strip()
        
        # 尝试提取 JSON 对象
        json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                triage_result = {
                    "action": parsed.get("action", "chat"),
                    "category": parsed.get("category", "通用咨询"),
                    "reply": parsed.get("reply", "")
                }
                print(f"[TRIAGE] JSON 解析成功: action={triage_result['action']}")
            except json.JSONDecodeError as e:
                print(f"[WARNING] JSON 解析失败: {e}, 原文: {json_str[:200]}")
    
    # 兜底：如果 JSON 解析失败
    if not triage_result:
        # 推断 action
        action = "chat"
        if output_text and ("form" in output_text.lower() or "转交" in output_text or "信息收集完毕" in output_text):
            action = "form"
        
        # 尝试用原始 LLM 输出作为回复（而不是报错）
        if raw_output and len(raw_output.strip()) > 10:
            # LLM 返回了内容但不是 JSON 格式，直接把自然语言当回复
            reply_text = raw_output.strip()
            # 清理可能残留的标签
            reply_text = re.sub(r'</?thinking>', '', reply_text).strip()
            reply_text = re.sub(r'</?output>', '', reply_text).strip()
            print(f"[TRIAGE] 兜底模式：使用原始输出作为回复（前50字）: {reply_text[:50]}...")
        elif last_error:
            reply_text = f"[调试信息] 分诊台错误: {last_error}。请检查 API Key 和网络配置。"
        else:
            reply_text = "您好，我是劳动法智能助理，请问有什么可以帮您的？"
        
        triage_result = {
            "action": action,
            "category": "通用咨询",
            "reply": reply_text
        }
        print(f"[TRIAGE] 兜底模式: action={action}")
    
    # AIMessage 只放纯回复文本，不放 thinking 标签
    # thinking 过程仅在服务端日志中记录，避免污染前端和后续 LLM 上下文
    ai_content = triage_result["reply"]
    
    if thinking_text:
        print(f"[TRIAGE] 思考过程: {thinking_text[:200]}...")
    
    print(f"[TARGET] [意图识别结果] 动作: {triage_result['action']}, 分类: {triage_result['category']}, 完善度: {completeness_pct}%")
    ai_reply_message = AIMessage(content=ai_content)
    return {"triage_result": triage_result, "messages": [ai_reply_message]}

def extract_output(text: str) -> str:
    import re
    match = re.search(r'<output>(.*?)</output>', text, re.DOTALL)
    if match: return match.group(1).strip()
    match = re.search(r'</thinking>(.*)', text, re.DOTALL)
    if match: return match.group(1).strip()
    return text.strip()

def fact_summarizer_node(state: LaborLawState) -> LaborLawState:
    """节点2：事实梳理员（使用轻量 LLM 提速，保留思考链）"""
    form_data = state.get("form_data", {})
    form_text = "\n".join([f"- {k}: {v}" for k, v in form_data.items()])
    prompt = f"""请根据以下案件信息梳理关键事实：\n【用户表单提交信息】：\n{form_text}
    请你必须先在 <thinking> 标签内进行沙盘推演和逻辑自洽检查。
    思考完成后，再在 <output> 标签内梳理：1. 争议焦点 2. 关键时间节点 3. 证据情况分析 4. 法律适用预判"""
    messages = [SystemMessage(content="你是劳动法律师助理"), HumanMessage(content=prompt)]
    return {"legal_facts_summary": extract_output(llm_fast.invoke(messages).content)}

def legal_researcher_node(state: LaborLawState) -> LaborLawState:
    """节点3：法条检索 + 案例参考（合并原并行双节点，减少1次LLM调用）"""
    print("\n[法条+案例专员] 正在查询知识库并检索参考案例...")
    summary = state.get("legal_facts_summary", "")
    if not summary: return {"relevant_laws": "暂无相关事实，无法检索法条", "similar_cases": ""}

    # 用轻量 LLM 快速提取检索词（替代 structured_output，更快）
    rewrite_prompt = f"根据以下案件事实，提取3个用于法律检索的中文关键词，用逗号分隔。不要输出其他内容。\n事实：{summary[:300]}"
    try:
        queries_text = llm_fast.invoke([HumanMessage(content=rewrite_prompt)]).content
        queries = [q.strip() for q in queries_text.split('，') if q.strip()][:3]
        if not queries: queries = [summary[:50]]
    except Exception:
        queries = [summary[:50]]

    # ==========================================
    # 🌟 优化一 & 优化二合并：动态地域过滤 + 交替抽取防挤占
    # ==========================================
    # 1. 提取用户所在地域
    user_location = state.get("form_data", {}).get("案件发生地", "")
    regions = ["北京", "上海", "天津", "重庆", "广东", "江苏", "浙江", "山东", "河南", "四川", "湖北", "湖南", "河北", "安徽", "辽宁", "福建", "陕西", "江西", "黑龙江", "广西", "云南", "贵州", "山西", "吉林", "内蒙古", "新疆", "甘肃", "海南", "宁夏", "青海", "西藏", "深圳", "广州"]
    
    target_region = "全国"
    for r in regions:
        if r in user_location:
            target_region = r
            break
            
    print(f"[地域过滤] 用户案件地: '{user_location}' -> 匹配规则: 检索【全国】与【{target_region}】法规")

    # 2. 跨维度检索（内存地域过滤）
    all_docs = []
    seen_content = set()
    retrieved_batches = []
    
    for q in queries:
        try:
            # 优先混合检索；图数据库不存在或异常时回退原向量检索。
            if hybrid_retriever is not None:
                hybrid_result = hybrid_retriever.retrieve(
                    q,
                    k_vector=20,
                    k_rules=8,
                    graph_depth=1,
                    jurisdiction=target_region,
                )
                from langchain_core.documents import Document

                docs = []
                for retrieved_rule in hybrid_result.rules:
                    rule = retrieved_rule.rule
                    conditions = "；".join(item.text for item in rule.conditions) or "无"
                    exceptions = "；".join(item.text for item in rule.exceptions) or "无"
                    procedures = "；".join(item.text for item in rule.procedures) or "无"
                    consequences = "；".join(item.text for item in rule.consequences)
                    for source in rule.sources:
                        graph_path = " → ".join(retrieved_rule.graph_path)
                        docs.append(Document(
                            page_content=(
                                f"《{source.law_name}》\n{source.article} {source.quote}\n"
                                f"【图谱规则】{rule.name}\n"
                                f"【适用条件】{conditions}\n"
                                f"【例外】{exceptions}\n"
                                f"【程序】{procedures}\n"
                                f"【法律后果】{consequences}"
                                + (f"\n【关联路径】{graph_path}" if graph_path else "")
                            ),
                            metadata={
                                "source": source.source_path or source.law_name,
                                "law_name": source.law_name,
                                "article": source.article,
                                "region": source.jurisdiction,
                                "category": "GraphRAG",
                                "chunk_id": source.chunk_id,
                                "rule_id": rule.rule_id,
                            },
                        ))
                docs.extend(hybrid_result.fallback_documents)
            else:
                docs = vectorstore.similarity_search(q, k=20)
            # 内存过滤：只保留符合地域条件的文档
            filtered_docs = []
            for doc in docs:
                region = doc.metadata.get("region", "全国")
                if target_region == "全国":
                    if region == "全国":
                        filtered_docs.append(doc)
                else:
                    if region in ("全国", target_region):
                        filtered_docs.append(doc)
                if len(filtered_docs) >= 4:
                    break
            retrieved_batches.append(filtered_docs)
        except Exception as e:
            print(f"[检索报错] 无法执行查询: {e}")
            continue
            
    # 4. 交替抽取（Round-Robin）: 确保每个关键词的 Top 1 都能入选
    if retrieved_batches:
        max_docs_per_query = max(len(batch) for batch in retrieved_batches)
        for i in range(max_docs_per_query):
            for batch in retrieved_batches:
                if i < len(batch):
                    doc = batch[i]
                    if doc.page_content not in seen_content:
                        seen_content.add(doc.page_content)
                        all_docs.append(doc)
                    
                    # 只要集齐最相关的 6 条法条就立刻停止，保护 Token
                    if len(all_docs) >= 6:
                        break
            if len(all_docs) >= 6:
                break
                
    # ── 构建编号法条列表 + 溯源 metadata ──
    relevant_sources = []
    if all_docs:
        for i, doc in enumerate(all_docs):
            # 从 page_content 提取条款号（如"第四十七条"）
            article_match = re.search(r'(第[一二三四五六七八九十百千\d]+条)', doc.page_content)
            article = article_match.group(1) if article_match else ""
            # 提取法律名称
            law_match = re.search(r'《(.+?)》', doc.page_content)
            law_name = law_match.group(1) if law_match else doc.metadata.get("law_name", "未知法规")
            # 截取正文前 300 字符作为摘要
            text_preview = doc.page_content[:300]
            relevant_sources.append({
                "id": str(i + 1),
                "source": law_name,
                "article": article,
                "text": text_preview,
                "region": doc.metadata.get("region", "全国"),
                "category": doc.metadata.get("category", ""),
            })
    
    # ── 构建带编号的 prompt ──
    numbered_docs_lines = []
    for src in relevant_sources:
        numbered_docs_lines.append(f"[{src['id']}] {src['text']}")
    numbered_docs = "\n\n".join(numbered_docs_lines) if numbered_docs_lines else "暂无法条"
    # ==========================================
    
    prompt = f"""你是一名精通中国劳动法的资深裁判者。
    【案件事实】：{summary}
    【相关法条（编号用于引用）】：{numbered_docs}

    ⚠️ 重要引用规则：当你引用上述法条时，必须在引用的条款后标注对应的编号，例如「根据《劳动合同法》第四十七条[1]」。
    如果同时引用多条法条，格式为「根据相关规定[1][3]」。
    
    请在 <thinking> 标签中排查法条冲突（注意特别法优于一般法，上位法优于下位法）。
    思考后在 <output> 标签输出：
    ## 法条适用分析
    1. 适用具体法律条款 2. 适用说明 3. 赔偿计算依据 4. 程序建议

    ## 参考案例要旨
    简述1个国内劳动争议领域的典型相似判例要旨及对本案参考价值。"""
    
    messages = [SystemMessage(content="你是精通法理的资深专家，必须用法条编号[1][2]标注引用"), HumanMessage(content=prompt)]
    result = extract_output(llm.invoke(messages).content)
    
    return {"relevant_laws": result, "similar_cases": "", "relevant_sources": relevant_sources}

def compliance_reviewer_node(state: LaborLawState) -> LaborLawState:
    """节点4 (汇合点)：合规审核员"""
    print("\n[合规审核员] 正在汇编最终报告...")
    facts = state.get("legal_facts_summary", "")
    laws = state.get("relevant_laws", "")
    feedback = state.get("reviewer_feedback", "")
    
    form_text = "\n".join([f"- {k}: {v}" for k, v in state.get("form_data", {}).items()])
    prompt = f"原始信息：\n{form_text}\n事实：\n{facts}\n法条分析：\n{laws}"
    
    if feedback:
        print(f"⚠️ 收到主编修改意见，开始重写：{feedback}")
        prompt += f"\n\n【主编打回修改意见】：\n{feedback}\n请务必严格修正上述漏洞！"
        
    prompt += """
请你在 <thinking> 标签内审视前置分析有无漏洞。思考后在 <output> 标签输出一份完整、精炼的合规法律建议报告。

⚠️ 【报告开头必须包含以下免责声明，原文照抄不可删改】：
> **⚠️ 重要提示：本报告由AI自动生成，可能存在错误或遗漏，仅作为对案情的简要初步分析，不构成正式法律意见，不建议作为最终行动指南。本报告并非律师专业建议。如涉案金额较大或案情复杂，强烈建议咨询专业劳动法律师获取帮助。**

报告正文必须包含以下四部分：

## 一、案情关键证据梳理
结合本案具体案情，罗列用户应收集的核心证据清单（每项写明证据名称、证明目的、取证方式/来源），并逐条指出证据收集中的注意事项与常见陷阱。

## 二、适用法律与操作指引
列出本案最核心的2-3条法律条款，每条必须包含：
- 法律名称与条款号
- 该条款在本案中的具体适用逻辑（为何适用、如何适用）
- 依据该条款用户可以主张的具体权利或赔偿项目

## 三、程序操作与实体策略
以「程序怎么走 + 实体权利怎么用」为主线，将程序性操作建议与实体法条运用融合在一起，按优先级排列：
- 第一步该做什么（对应哪条法律依据）
- 后续步骤及对应策略
- 每一步的风险点与应对方式

## 四、综合建议
简要总结本案的总体策略方向、最优解决路径（协商/仲裁/诉讼的利弊判断），以及用户当前最应关注的紧迫事项。

⚠️ 格式要求：禁止使用表格（Markdown table），所有内容必须用文字段落和列表呈现。
⚠️ 内容要求：四部分缺一不可，每部分必须充分展开，不能省略。
⚠️ 严格字数限制：输出正文必须在1800-2500字之间。语言精炼，直击要害，不要赘述。"""
    messages = [SystemMessage(content="你是资深劳动法律师"), HumanMessage(content=prompt)]
    return {"final_review": extract_output(llm.invoke(messages).content)}

# 🌟 新增：质检员把关
def quality_inspector_node(state: LaborLawState) -> LaborLawState:
    """节点5：主编质检员（打回重写一次后直接通过，不再二次审查）"""
    print("\n[主编质检员] 正在快速审核...")
    review = state.get("final_review", "")
    retry_count = state.get("retry_count", 0)
    
    # 已经重写过了，直接通过，省掉一次 LLM 调用
    if retry_count >= 1:
        print(f"[QA] ⏭️ 已重写过一次，直接通过 | 重试: {retry_count}")
        return {
            "reviewer_feedback": "",
            "retry_count": retry_count + 1,
            "is_pass_flag": True
        }
    
    # === 插入的防幻觉审计增强代码 ===
    form_text = "\n".join([f"- {k}: {v}" for k, v in state.get("form_data", {}).items()])
    laws = state.get("relevant_laws", "无检索法条")
    facts = state.get("legal_facts_summary", "无事实摘要")
    
    prompt = f"""你是一名严苛的带教律师，正在对实习生出具的法律报告进行出厂前的【交叉合规审计】。
    必须审查以下三点，有任何一点不符合则打回 (FAIL) 并给出具体修改意见：
    1. 【诉求响应】：是否正面回应了用户的核心诉求？
    2. 【防幻觉核查】：报告中引用的法条，是否严格基于下方提供的【检索依据】？杜绝任何捏造法条！
    3. 【逻辑闭环】：适用的法条与认定的事实之间是否存在逻辑脱节？

    【原始卷宗】：\n{form_text}
    【案件事实摘要】：\n{facts}
    【RAG 检索到的真实法条依据】：\n{laws}
    
    【待审法律报告】：\n{review[:1500]}
    
    请严格按要求输出 PASS 或 FAIL 及意见。"""
    # === 增强完毕 ===
    
    try:
        qa_out = llm_fast.with_structured_output(QualityOutput).invoke([HumanMessage(content=prompt)])
        is_pass, feedback = qa_out.is_pass, qa_out.feedback
    except Exception as e:
        print(f"[QA ERROR] 质检结构化输出失败，换 llm 重试: {e}")
        try:
            qa_out = llm.with_structured_output(QualityOutput).invoke([HumanMessage(content=prompt)])
            is_pass, feedback = qa_out.is_pass, qa_out.feedback
        except Exception as e2:
            print(f"[QA ERROR] 重试也失败，强行放行: {e2}")
            is_pass, feedback = True, "无"
        
    print(f"[QA] {'✅ 通过' if is_pass else '❌ 打回'} | 重试: {retry_count} | 意见: {feedback}")

    return {
        "reviewer_feedback": feedback if not is_pass else "",
        "retry_count": retry_count + 1,
        "is_pass_flag": is_pass
    }

# ==========================================
# 6. 构建 LangGraph 工作流
# ==========================================
def _init_langgraph_app():
    """构建 LangGraph 多智能体工作流"""
    global app
    
    print(">>> 正在构建精简高速多智能体架构流...")
    workflow = StateGraph(LaborLawState)

    workflow.add_node("summarizer", summarize_conversation_node)
    workflow.add_node("triage", triage_node)
    workflow.add_node("fact_summarizer", fact_summarizer_node)
    workflow.add_node("legal_researcher", legal_researcher_node)
    workflow.add_node("compliance_reviewer", compliance_reviewer_node)
    workflow.add_node("quality_inspector", quality_inspector_node)

    workflow.set_entry_point("summarizer")
    workflow.add_edge("summarizer", "triage")

    # 路由 1：分诊
    def route_after_triage(state: LaborLawState):
        return "process_case" if state.get("triage_result", {}).get("action") == "form" else "end"

    workflow.add_conditional_edges("triage", route_after_triage, {"process_case": "fact_summarizer", "end": END})

    # 串行流水线（合并原并行双节点，减少1次LLM调用）
    workflow.add_edge("fact_summarizer", "legal_researcher")
    workflow.add_edge("legal_researcher", "compliance_reviewer")
    workflow.add_edge("compliance_reviewer", "quality_inspector")

    # 质检纠错环
    def route_after_qa(state: LaborLawState):
        if state.get("is_pass_flag", True) or state.get("retry_count", 0) >= 2:
            return "end"
        return "retry"

    workflow.add_conditional_edges("quality_inspector", route_after_qa, {"end": END, "retry": "compliance_reviewer"})

    # 编译并返回 app
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory, interrupt_before=["fact_summarizer"])
