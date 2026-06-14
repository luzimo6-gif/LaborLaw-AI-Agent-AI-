# -*- mode: python ; coding: utf-8 -*-
"""
劳动法律智能体_根号三 — PyInstaller 打包配置
方案B：主程序体不包含 data/ 知识库，用户需单独下载
"""

block_cipher = None

# ── 打包数据文件（不含 data/ 知识库目录）──
datas_list = [
    ('UI 图片', 'UI 图片'),              # 界面图片资源
    ('version.txt', '.'),                 # 版本号
    ('users.json.example', '.'),          # 默认用户配置模板
    ('劳动法AI Agent 用户服务协议.docx', '.'),  # 用户协议
    ('backend.py', '.'),                  # 后端模块
    ('simple_vectorstore.py', '.'),       # 向量库模块
    ('build_db.py', '.'),                 # 建库脚本（供高级用户使用）
    ('convert_doc_to_docx.py', '.'),      # 文档转换工具
]

# ── 需要强制导入的隐式依赖 ──
hidden_imports_list = [
    'nicegui', 'nicegui.native', 'nicegui.ui',
    'langchain', 'langgraph', 'langchain_openai', 'langchain_community',
    'langchain_core', 'langchain_text_splitters',
    'simple_vectorstore', 'backend',
    'numpy', 'requests', 'pymupdf', 'docx2txt',
    'json', 'hashlib', 'uuid', 're', 'queue', 'threading', 'urllib', 'tempfile',
    'pywebview', 'fastapi', 'uvicorn', 'starlette', 'jinja2', 'aiofiles',
    'pydantic', 'pydantic_core',
    'langchain_core.messages', 'langchain_core.documents',
    'langchain_core.embeddings',
    'langchain.embeddings.base',
]

a = Analysis(
    ['gui_nice.py'],
    pathex=[],
    binaries=[],
    datas=datas_list,
    hiddenimports=hidden_imports_list,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='劳动法律智能体_根号三',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,              # 不显示命令行窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',        # 应用图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='劳动法律智能体_根号三',
)
