#!/usr/bin/env python3
"""
劳动法律师智能助理 - NiceGUI 桌面版（现代化异步重构）
布局参照原 tkinter GUI，全面拥抱 NiceGUI 最佳实践：
- @ui.refreshable 局部渲染，消灭全局刷新
- ui.chat_message 原生聊天气泡
- async/await + run.io_bound 替代线程+队列轮询
- Tailwind CSS 替代硬编码 style
"""
import os
import sys
import json
import uuid
import re
import hashlib
from datetime import datetime

# ── 路径初始化 ──
# PyInstaller 打包后资源文件解压在 sys._MEIPASS 临时目录
if getattr(sys, 'frozen', False):
    _BASE_DIR = sys._MEIPASS
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCRIPT_DIR = _BASE_DIR
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

# 用户数据目录（打包后程序本体只读，用户数据需写到这里）
_USER_DATA_DIR = os.path.join(os.path.expanduser('~'), 'Documents', '劳动法律智能体_根号三')
os.makedirs(_USER_DATA_DIR, exist_ok=True)

from nicegui import ui, app, run

# ══════════════════════════════════════════
# 1. 常量与配色（与 tkinter 版完全一致）
# ══════════════════════════════════════════
APP_TITLE = "AI 劳动法"
APP_VERSION_FILE = os.path.join(SCRIPT_DIR, "version.txt")
USERS_FILE = os.path.join(_USER_DATA_DIR, "users.json")
FEEDBACK_DB_FILE = os.path.join(_USER_DATA_DIR, "feedback.json")

COLOR_PRIMARY = "#0F2C5C"
COLOR_ACCENT = "#E6B800"
COLOR_BG = "#F0F4F8"
COLOR_CARD = "#FFFFFF"
COLOR_TEXT = "#1E293B"
COLOR_TEXT_SECONDARY = "#64748B"
COLOR_BORDER = "#CBD5E1"
COLOR_SUCCESS = "#16A34A"
COLOR_WARNING = "#EA580C"
COLOR_ERROR = "#DC2626"
COLOR_INFO = "#2563EB"
COLOR_SIDEBAR_BG = "#F7F9FC"

USER_AVATAR_URL = "/ui_images/avatars/user-client.png"
AI_AVATAR_URL = "/ui_images/avatars/ai-assistant.png"

API_PROVIDER_OPTIONS = [
    ("阿里云百炼 (Qwen)", "qwen"),
    ("DeepSeek 官方", "deepseek"),
    ("硅基流动 (SiliconFlow)", "siliconflow"),
    ("自定义 OpenAI 兼容接口", "custom"),
]
API_PROVIDER_DEFAULTS = {
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-7B-Instruct"},
}

# ── 审计轨迹：LangGraph 节点 → 中文友好描述 ──
NODE_FRIENDLY_NAMES = {
    "summarizer":          "📝 记忆压缩中（上下文工程）",
    "triage":              "🔍 分诊台 AI 正在分析意图",
    "fact_summarizer":     "📋 事实梳理员正在整理案情",
    "legal_researcher":    "📚 法条检索 + 案例专员正在查询知识库",
    "compliance_reviewer": "⚖️ 合规审核员正在汇编最终报告",
    "quality_inspector":   "✅ 主编质检员正在审核报告质量",
}

# ── 流式迭代器（用于逐步消费 LangGraph stream） ──
_stream_iter = None

_backend_cache = {}

# ── 暗黑模式全局引用 ──
dark = None

# ══════════════════════════════════════════
# 2. 工具函数（与 tkinter 版完全一致，未修改业务逻辑）
# ══════════════════════════════════════════
def read_version():
    if os.path.exists(APP_VERSION_FILE):
        with open(APP_VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "v1.0.0"

def hash_password(password: str, salt: str | None = None) -> str:
    """PBKDF2 加盐哈希，兼容旧版无盐 SHA-256"""
    if salt is None:
        salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"pbkdf2:sha256:{salt}${key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码，兼容旧版无盐 SHA-256 和新版 PBKDF2"""
    # 新版 PBKDF2 格式：pbkdf2:sha256:<salt>$<hash>
    if stored_hash.startswith("pbkdf2:sha256:"):
        try:
            _, _, salt_and_hash = stored_hash.split(":", 2)
            salt, hash_hex = salt_and_hash.split("$")
            key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
            return key.hex() == hash_hex
        except (ValueError, AttributeError):
            return False
    # 旧版无盐 SHA-256 兼容
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash


def upgrade_password_if_needed(username: str, password: str, users: dict):
    """若用户密码仍为旧版无盐哈希，验证后自动升级为 PBKDF2"""
    stored_hash = users[username].get("password", "")
    if not stored_hash.startswith("pbkdf2:"):
        if hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_hash:
            users[username]["password"] = hash_password(password)
            save_users(users)

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # 尝试从打包资源中复制默认配置（如果有 users.json.example）
    example_file = os.path.join(SCRIPT_DIR, "users.json.example")
    if os.path.exists(example_file):
        with open(example_file, "r", encoding="utf-8") as f:
            default = json.load(f)
        save_users(default)
        return default
    default = {
        "lzy": {
            "password": hash_password("123456"),
            "name": "罗志远",
            "role": "admin",
            "api_key": "",
            "api_provider": "qwen",
            "base_url": "",
            "model": "qwen-plus"
        }
    }
    save_users(default)
    return default

def save_users(users: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def authenticate(username: str, password: str) -> bool:
    users = load_users()
    if username not in users:
        return False
    return verify_password(password, users[username]["password"])

def create_user(username: str, password: str, name: str, role: str = "user",
                api_key: str = "", api_provider: str = "qwen",
                base_url: str = "", model: str = "") -> bool:
    users = load_users()
    if username in users:
        return False
    preset = API_PROVIDER_DEFAULTS.get(api_provider, {})
    users[username] = {
        "password": hash_password(password),
        "name": name,
        "role": role,
        "api_key": api_key,
        "api_provider": api_provider,
        "base_url": base_url or preset.get("base_url", ""),
        "model": model or preset.get("model", ""),
    }
    save_users(users)
    return True

def delete_user(username: str) -> bool:
    users = load_users()
    if username not in users:
        return False
    del users[username]
    save_users(users)
    return True

def update_user_api(username: str, api_key: str, api_provider: str, base_url: str, model: str) -> bool:
    users = load_users()
    if username not in users:
        return False
    users[username]["api_key"] = api_key
    users[username]["api_provider"] = api_provider
    users[username]["base_url"] = base_url
    users[username]["model"] = model
    save_users(users)
    return True

def get_user_api_config(username: str) -> dict:
    users = load_users()
    user = users.get(username, {})
    return {
        "api_key": user.get("api_key", ""),
        "api_provider": user.get("api_provider", "qwen"),
        "base_url": user.get("base_url", ""),
        "model": user.get("model", ""),
    }

def load_backend(username: str = None):
    global _backend_cache
    if username and username in _backend_cache:
        return _backend_cache[username]
    try:
        from backend import init_backend, app, llm, llm_fast, embeddings
        if username:
            api_config = get_user_api_config(username)
            if api_config.get("api_key"):
                init_backend(api_config)
                from backend import app as _app, llm as _llm, llm_fast as _llm_fast, embeddings as _emb
                _backend_cache[username] = (_app, _llm, _llm_fast, _emb)
                return _backend_cache[username]
            else:
                return None, None, None, None
        else:
            if app is not None:
                return app, llm, llm_fast, embeddings
            return None, None, None, None
    except Exception as e:
        print(f"[WARN] 后端加载失败: {e}")
        return None, None, None, None

def evaluate_form_completeness(form_data):
    if not form_data:
        return 0, [], "卷宗为空，请开始描述案情"
    total = len(form_data)
    filled = {k: v for k, v in form_data.items() if v and v.strip()}
    filled_count = len(filled)
    missing = [k for k, v in form_data.items() if not v or not v.strip()]
    pct = int(filled_count / total * 100) if total > 0 else 0
    core_fields = ["核心诉求", "详细经过"]
    core_filled = sum(1 for f in core_fields if form_data.get(f, "").strip())
    if pct >= 80:
        suggestion = "信息充分，可以生成报告"
    elif core_filled >= 1 and pct >= 50:
        suggestion = f"核心信息已有，建议补充：{'、'.join(missing[:2])}"
    elif core_filled == 0:
        suggestion = "缺少核心诉求和案情经过，请继续描述"
    else:
        suggestion = f"还需补充：{'、'.join(missing)}"
    return pct, missing, suggestion

# ══════════════════════════════════════════
# 3. 用户服务协议文本
# ══════════════════════════════════════════
USER_AGREEMENT_TEXT = """劳动法AI Agent 用户服务协议
最新更新日期：2026.06.06

欢迎您使用劳动法AI Agent（以下简称"本服务"）。在注册、访问或使用本服务之前，请您务必仔细阅读并透彻理解本《用户服务协议》（以下简称"本协议"）。如果您不同意本协议的任何条款，请立即停止访问或使用本服务。

第一条：服务的性质与"非授权执业"严正声明
1.1 非专业法律意见：本服务是一个基于大语言模型与自然语言处理技术的自动化工具，其生成的所有内容（包括但不限于劳动合同条款分析、裁员风险评估、经济补偿金计算、仲裁策略建议等）均仅作为统计学意义上的"法律参考信息"提供。本服务及其背后的算法模型不具备任何司法管辖区的律师执业资格，其输出在任何情况下均不构成，也绝不得被解释为具有法律约束力的"法律建议"（Legal Advice）或专业法律咨询。

1.2 无律师-客户关系：使用本服务绝对不会在本平台（含开发者、运营方及关联主体）之间建立任何形式的"律师-客户关系"。本平台对您不负有律师的信义义务（Duty of Loyalty）或职业责任。

1.3 特权丧失警告：由于不存在律师-客户关系，您向本平台输入的任何案件事实、商业机密、员工薪酬数据或诉讼策略，均不受律师-客户保密特权（Attorney-Client Privilege）保护。在潜在的法律诉讼中，您的输入提示词（Prompts）及AI生成的响应内容存在被司法机关合法调取并作为证据的风险，请您切勿输入敏感的个人隐私或企业绝密信息。

第二条：AI"幻觉"风险与信赖利益切断
2.1 技术局限性：生成式人工智能技术存在固有的概率性、不可解释性及数据滞后性。本服务可能会产生看似合理、专业，但实质上存在事实错误、遗漏、虚构法条（即"AI幻觉"）或具有误导性的内容。

2.2 人工审查义务：您完全接受并同意，使用本服务输出内容的风险由您自行承担，您绝不能将本服务输出作为事实信息的唯一来源或专业法律建议的替代品。在将本服务生成的任何文本用于具有实际法律效力的场合（如发送解雇通知、签署协议、提交仲裁庭）之前，您必须交由具有合格资质且持有执照的专业律师进行人工审查与核实。

第三条：商业使用限制与平台权利
3.1 禁止商业化滥用：除非您已获得本平台的明确书面商业授权，否则您仅可出于个人学习、内部合规自查或学术研究等非商业目的使用本服务。您不得利用本服务直接或间接牟利。

3.2 禁止反向工程：您不得尝试对本服务的底层模型、算法或源代码进行反向工程、反编译或拆解。

第四条：用户行为规范与算法合规责任
4.1 合法使用：您的输入内容及相关指令必须严格遵守适用法律的规定，您须对因输入违规内容造成的所有后果承担全部责任。

4.2 禁止算法歧视：在处理劳动法相关问题（如招聘筛查、裁员评估）时，您不得利用本服务实施基于种族、性别、年龄、宗教信仰或生育状况的非法歧视。

第五条：知识产权与生成内容标识
5.1 权利归属：您在享有使用本服务的同时，需确保您输入的数据合法且未侵犯第三方的知识产权。

5.2 透明度与标识义务：当您向第三方出示、分享由本平台生成的内容时，您负有强制性的透明度义务，必须在合理位置添加显式标识，明确告知该内容"由人工智能（AI）生成"。

第六条：免责声明与责任限制
6.1 "按原样"提供：本服务乃"按原样"（AS IS）及"现有状况"提供，平台不对服务的适销性、针对特定用途的适用性、准确性、不中断性及非侵权性作出任何明示或暗示的保证。

6.2 责任上限：在适用法律允许的最大范围内，无论基于何种法律理论，本平台、开发者及其关联方对您因使用或无法使用本服务而导致的任何直接、间接、附带、特殊、后果性或惩罚性损害概不负责。

第七条：其他条款
7.1 协议修改：本平台保留在任何时候修改、更新本协议的权利。重大变更将通过页面弹窗或网站公告的形式通知您。

7.2 争议解决与管辖：本协议的签订、履行、解释及争议解决均适用中华人民共和国法律。"""

# ══════════════════════════════════════════
# 4. 全局状态（数据结构不变）
# ══════════════════════════════════════════
class GlobalState:
    def __init__(self):
        self.agreement_accepted = False
        self.logged_in = False
        self.username = ""
        self.user_role = ""
        self.user_name = ""
        self.current_page = "login"
        self.main_subpage = "chat"
        # 聊天状态
        self.messages = []
        self.form_data = {"案件发生地": "", "单位名称": "", "平均月薪": "", "时间节点": "", "核心诉求": "", "详细经过": ""}
        self.ai_mode = "PRO"
        self.ai_mode_confirmed = False
        self.ready_for_analysis = False
        self.analysis_result = None
        self.report_generated = False
        self.context_round_count = 0
        self.thread_id = ""
        self.uploaded_files = []  # 已上传文件列表 [{"name": "合同.pdf", "path": "...", "size": 12345}]
        self._app = None
        self._llm = None
        self._llm_fast = None
        self._embeddings = None
        self._is_streaming = False

state = GlobalState()

# ── 全局键盘快捷键处理 ──
def _handle_global_key(e, focus_callback):
    """处理全局键盘事件（NiceGUI 3.x KeyEventArguments）"""
    # / 键：聚焦输入框
    if e.action.keydown and e.key.name == '/':
        focus_callback()
    # Ctrl+K：聚焦输入框
    if e.action.keydown and e.key.name == 'k' and e.modifiers.ctrl:
        focus_callback()


async def _on_input_keydown(e, input_box, send_callback):
    """处理输入框键盘事件：Enter 发送，Shift+Enter 换行"""
    if e.action.keydown and e.key.name == 'Enter' and not e.modifiers.shift:
        await send_callback()


# ── 暗黑模式图标切换 ──
_dark_btn_ref = None

def _set_dark_btn_ref(ref):
    global _dark_btn_ref
    _dark_btn_ref = ref

def _update_dark_icon():
    """根据当前 dark_mode 状态更新按钮图标"""
    global _dark_btn_ref, dark
    if _dark_btn_ref is not None and dark is not None:
        icon_name = 'light_mode' if dark.value else 'dark_mode'
        _dark_btn_ref.props(f'icon={icon_name}')


# ══════════════════════════════════════════
# 用户反馈数据存储（数据飞轮）
# ══════════════════════════════════════════
# FEEDBACK_DB_FILE 已在顶部定义为用户数据目录下的路径

def _load_feedback_db() -> list:
    """加载反馈数据库"""
    if os.path.exists(FEEDBACK_DB_FILE):
        try:
            with open(FEEDBACK_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _save_feedback_db(data: list):
    """保存反馈数据库"""
    with open(FEEDBACK_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_user_feedback(feedback_type: str, thread_id: str, user_query: str,
                       ai_response: str, citations: dict = None,
                       correction: str = ""):
    """
    保存用户反馈到本地 JSON 数据库。
    
    参数:
        feedback_type: "positive" 或 "negative"
        thread_id: 当前案件编号
        user_query: 用户上一轮的提问
        ai_response: AI 的回答内容
        citations: 当时的引用上下文
        correction: 人工纠正意见（仅 negative 反馈）
    """
    record = {
        "timestamp": datetime.now().isoformat(),
        "thread_id": thread_id,
        "feedback_type": feedback_type,
        "user_query": user_query,
        "ai_response": ai_response[:2000],  # 截断过长的回答
        "citations": citations or {},
        "correction": correction,
        "username": state.username,
    }
    db = _load_feedback_db()
    db.append(record)
    _save_feedback_db(db)
    print(f"[反馈] 已记录 {feedback_type} 反馈 -> {FEEDBACK_DB_FILE}")


# ══════════════════════════════════════════
# 5. 全局 CSS — 仅保留必须用硬编码的场景（侧边栏、导航栏等容器级样式）
# 注意：Quasar 暗黑模式添加的类名是 .body--dark，不是 body.dark
# ══════════════════════════════════════════
ui.add_css(f"""
body {{ background: #ffffff; font-family: 'Microsoft YaHei', 'Segoe UI', 'Google Sans', sans-serif; }}
.body--dark {{ background: #131314; }}
.body--dark body {{ background: #131314; }}
.agreement-text {{ white-space: pre-wrap; font-size: 12px; line-height: 1.6; }}
.body--dark .agreement-text {{ color: #CBD5E1; }}
/* 暗黑模式下 Quasar 卡片和输入框 */
.body--dark .q-card {{ background: #1E293B !important; border-color: #334155 !important; color: #E2E8F0 !important; }}
.body--dark .q-input {{ color: #E2E8F0; }}
.body--dark .q-field__native {{ color: #E2E8F0; }}
.body--dark .q-field__label {{ color: #94A3B8; }}
.body--dark .text-slate-500 {{ color: #94A3B8 !important; }}
.body--dark .text-slate-600 {{ color: #CBD5E1 !important; }}
.body--dark .text-slate-700 {{ color: #E2E8F0 !important; }}
.body--dark .text-slate-800 {{ color: #F1F5F9 !important; }}
/* 注意：不再全局强制覆盖 bg-white / bg-[#f0f4f9] / bg-[#f8fafd]，
   改由 Tailwind dark: 前缀在元素级别精确控制 */
.body--dark .border-slate-200 {{ border-color: #334155 !important; }}
.body--dark .border-slate-700 {{ border-color: #475569 !important; }}
/* 聊天气泡暗黑适配 */
.body--dark .q-message {{ color: #E2E8F0; }}
/* Composer 输入区暗黑适配 */
.body--dark .q-textarea[borderless] .q-field__native {{ color: #E2E8F0; }}
/* scroll_area 暗黑适配 */
.body--dark .q-scrollarea {{ color: #E2E8F0; }}
/* 文件上传区域暗黑适配 */
.body--dark .q-uploader {{ background: #1e1f22; color: #E2E8F0; border-color: #3c4043; }}
.body--dark .q-uploader__header {{ background: #282a2c; }}
.body--dark .q-uploader__file {{ background: #1e1f22; }}
/* 下拉菜单暗黑适配 */
.body--dark .q-menu {{ background: #282a2c; color: #E2E8F0; }}
.body--dark .q-item {{ color: #E2E8F0; }}
.body--dark .q-item:hover {{ background: #3c4043; }}
/* 登录页暗黑适配 */
.body--dark .bg-slate-50 {{ background: #0F172A !important; }}
.body--dark .bg-slate-100 {{ background: #1E293B !important; }}
""", shared=True)

# ══════════════════════════════════════════
# 6. 页面路由 — 单一 / 路由，按状态渲染
# ══════════════════════════════════════════
main_container = None

@ui.page('/')
def home_page():
    global main_container
    with ui.row().classes('overflow-x-hidden max-w-full').style('width: 100vw; max-width: 100vw; height: 100vh; display: flex !important; flex-direction: column; overflow: hidden;') as container:
        main_container = container
        if not state.agreement_accepted:
            render_agreement()
        elif not state.logged_in:
            render_login()
        else:
            render_main()

# ══════════════════════════════════════════
# 7. 协议弹窗
# ══════════════════════════════════════════
def render_agreement():
    with ui.dialog(value=True).props('maximized') as dialog:
        with ui.card().classes('w-full max-w-3xl'):
            ui.label('📄 用户服务协议').classes('text-lg font-bold').style(f'color:{COLOR_PRIMARY}')
            ui.label('请仔细阅读以下协议。您必须同意后才能使用本软件。').classes('text-sm text-slate-500')
            ui.separator()
            with ui.scroll_area().classes('h-96'):
                ui.label(USER_AGREEMENT_TEXT).classes('agreement-text')
            ui.separator()
            with ui.row().classes('gap-4 justify-center'):
                def on_agree():
                    state.agreement_accepted = True
                    dialog.close()
                    ui.navigate.to('/')

                def on_disagree():
                    dialog.close()
                    ui.notify('感谢您的关注，程序将退出', type='warning')
                    app.shutdown()

                ui.button('✅ 我已阅读并同意', on_click=on_agree)\
                    .props('color=primary').classes('px-6 py-3')
                ui.button('❌ 不同意并退出', on_click=on_disagree)\
                    .props('outline color=negative').classes('px-6 py-3')

# ══════════════════════════════════════════
# 8. 登录页面
# ══════════════════════════════════════════
login_show_register = False

def render_login():
    global login_show_register

    with ui.column().classes('items-center justify-center h-full w-full').style(
        'background-image: url(\"/ui_images/UI桌面设计.png\"); '
        'background-size: cover; background-position: center; '
        'background-repeat: no-repeat;'
    ):
        with ui.card().classes('p-8 w-full max-w-md backdrop-blur-sm').style(
            f'border:1px solid {COLOR_BORDER}; '
            'background: rgba(255,255,255,0.55);'
        ):
            with ui.column().classes('items-center w-full'):
                ui.label('⚖️').style(f'font-size:48px; color:{COLOR_ACCENT}')
                ui.label(APP_TITLE).style(f'font-size:22px; font-weight:bold; color:{COLOR_PRIMARY}')
                ui.label('智能法律咨询系统').classes('text-xs text-slate-500 dark:text-slate-400')

            ui.separator()

            # 登录/注册切换
            with ui.row().classes('gap-2 justify-center'):
                login_tab = ui.button('🔐 登录', on_click=lambda: switch_tab(False))
                reg_tab = ui.button('📝 注册', on_click=lambda: switch_tab(True))
                def update_tab_style():
                    if login_show_register:
                        login_tab.props('outline color=primary')
                        reg_tab.props('color=primary')
                    else:
                        login_tab.props('color=primary')
                        reg_tab.props('outline color=primary')
                update_tab_style()

            ui.separator()

            form_container = ui.column().classes('w-full')

            def switch_tab(show_reg):
                global login_show_register
                login_show_register = show_reg
                update_tab_style()
                form_container.clear()
                with form_container:
                    if show_reg:
                        build_register_form()
                    else:
                        build_login_form()

            with form_container:
                build_login_form()

            ui.separator()
            ui.label(f'版本 {read_version()}').classes('text-xs text-slate-400 self-center')


def build_login_form():
    login_error = ui.label('').classes('text-xs text-red-600')

    username_input = ui.input('用户名').classes('w-full').props('outlined dense')
    password_input = ui.input('密码').classes('w-full').props('outlined dense type=password')

    def do_login():
        uname = (username_input.value or '').strip()
        pwd = password_input.value or ''
        if not uname or not pwd:
            login_error.set_text('请输入用户名和密码')
            return
        if authenticate(uname, pwd):
            users = load_users()
            user = users.get(uname, {})
            # 自动升级旧版无盐 SHA-256 哈希为 PBKDF2
            upgrade_password_if_needed(uname, pwd, users)
            state.username = uname
            state.user_role = user.get("role", "user")
            state.user_name = user.get("name", uname)
            state.logged_in = True
            state.thread_id = f"case_{uname}_{uuid.uuid4().hex[:6]}"
            state._app, state._llm, state._llm_fast, state._embeddings = load_backend(uname)
            ui.navigate.to('/')
        else:
            login_error.set_text('用户名或密码错误')

    ui.button('登  录', on_click=do_login).props('color=primary').classes('w-full mt-2')


def build_register_form():
    reg_error = ui.label('').classes('text-xs text-red-600')
    reg_success = ui.label('').classes('text-xs text-green-600')

    ui.label('━━ 账号信息 ━━').style(f'color:{COLOR_PRIMARY}').classes('text-xs font-bold')
    reg_username = ui.input('用户名 *').classes('w-full').props('outlined dense')
    reg_name = ui.input('姓名').classes('w-full').props('outlined dense')
    reg_password = ui.input('密码 *').classes('w-full').props('outlined dense type=password')
    reg_confirm = ui.input('确认密码 *').classes('w-full').props('outlined dense type=password')

    ui.separator()

    ui.label('━━ API 配置（必填）━━').style(f'color:{COLOR_ACCENT}').classes('text-xs font-bold')
    ui.label('请填写您的 API Key，数据仅存储在本地').classes('text-xs text-slate-400')

    provider_var = ui.select(
        label='API 平台 *',
        options={v: t for t, v in API_PROVIDER_OPTIONS},
        value='qwen'
    ).classes('w-full').props('outlined dense')

    reg_api_key = ui.input('API Key *').classes('w-full').props('outlined dense type=password')
    reg_base_url = ui.input('Base URL').classes('w-full').props('outlined dense')
    reg_model = ui.input('模型名称').classes('w-full').props('outlined dense')

    def on_provider_change(e=None):
        p = provider_var.value
        defaults = API_PROVIDER_DEFAULTS.get(p, {})
        reg_base_url.value = defaults.get("base_url", "")
        reg_model.value = defaults.get("model", "")
    provider_var.on('update:model-value', on_provider_change)
    on_provider_change()

    def do_register():
        uname = (reg_username.value or '').strip()
        name = (reg_name.value or '').strip()
        pwd = reg_password.value or ''
        confirm = reg_confirm.value or ''
        api_key = (reg_api_key.value or '').strip()
        provider = provider_var.value
        base_url = (reg_base_url.value or '').strip()
        model = (reg_model.value or '').strip()

        reg_error.set_text('')
        reg_success.set_text('')

        if not uname or not pwd:
            reg_error.set_text('用户名和密码为必填')
            return
        if pwd != confirm:
            reg_error.set_text('两次密码不一致')
            return
        if not api_key:
            reg_error.set_text('API Key 为必填')
            return

        ok = create_user(uname, pwd, name, "user", api_key, provider, base_url, model)
        if not ok:
            reg_error.set_text('用户名已存在')
            return
        reg_success.set_text('注册成功！请切换到登录页面登录')

    with ui.row().classes('gap-2'):
        ui.button('注  册', on_click=do_register).props('color=primary').classes('flex-1')
        ui.button('返回登录', on_click=lambda: switch_tab(False)).props('outline color=primary').classes('flex-1')


def switch_tab(show_reg):
    global login_show_register
    login_show_register = show_reg
    ui.navigate.to('/')

# ══════════════════════════════════════════
# 9. 主页面（侧边栏 + 内容区）
# ══════════════════════════════════════════

# 注入暗黑模式下背景图适配样式
ui.add_body_html('''
<style>
  /* 暗黑模式下背景图容器加暗色遮罩 */
  .dark .bg-main-wrapper {
    position: relative;
  }
  .dark .bg-main-wrapper::before {
    content: "";
    position: absolute;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 0;
    pointer-events: none;
  }
  /* 暗黑模式：顶部栏半透明深色 */
  .dark .bg-main-topbar {
    background: rgba(20,20,30,0.7) !important;
    backdrop-filter: blur(8px);
  }
  /* 暗黑模式：左侧边栏半透明深色 */
  .dark .bg-main-sidebar {
    background: rgba(20,22,30,0.85) !important;
  }
  /* 暗黑模式：中间聊天区半透明深色 */
  .dark .bg-main-chat {
    background: rgba(24,26,36,0.78) !important;
  }
  /* 暗黑模式：右侧表单面板半透明深色 */
  .dark .bg-main-panel {
    background: rgba(20,22,30,0.85) !important;
  }
  /* 暗黑模式：Composer 输入区半透明深色 */
  .dark .bg-main-composer {
    background: rgba(18,20,28,0.85) !important;
  }
  /* 暗黑模式：卷宗卡片 */
  .dark .bg-main-card {
    background: rgba(22,24,34,0.82) !important;
  }
</style>
''', shared=True)

def render_main():
    global dark
    # 初始化暗黑模式（使用 NiceGUI 原生 dark_mode）
    if dark is None:
        dark = ui.dark_mode()

    # ════════════ 背景图层：使用 UI主页背景.png，撑满全屏 ════════════
    with ui.element('div').classes('w-full max-w-full h-full overflow-x-hidden bg-main-wrapper').style(
        'background-image: url(\"/ui_images/UI主页背景.png\"); '
        'background-size: cover; background-position: center; '
        'background-repeat: no-repeat; '
        'display: flex; flex-direction: column; overflow-x: hidden;'
    ):

        # ════════════ Gemini 风格顶部栏：半透明背景，极简 ════════════
        with ui.row().classes('w-full max-w-full items-center justify-between px-5 py-2 shrink-0 overflow-hidden bg-main-topbar').style(
            'height: 48px; min-height: 48px; '
            'background: rgba(255,255,255,0.6); backdrop-filter: blur(8px);'
        ):
            # 左侧：小字 APP 名称（非深色背景，融入聊天区）
            ui.label(APP_TITLE).classes('text-sm font-semibold text-slate-500 dark:text-slate-400')
            ui.space()
            # 右侧：角色信息 + 暗黑切换 + 退出
            role_tag = '🔒 管理员' if state.user_role == 'admin' else '👤 用户'
            ui.label(f'{role_tag}  {state.user_name}')\
                .classes('text-xs text-slate-400 dark:text-slate-500 mr-2')
            dark_btn = ui.button(icon='dark_mode', on_click=lambda: (dark.toggle(), _update_dark_icon()))\
                .props('flat round').classes('text-slate-500 dark:text-slate-400').tooltip('切换日/夜间模式')
            dark_btn.bind_icon_from(dark, 'value', lambda v: 'light_mode' if v else 'dark_mode')
            _set_dark_btn_ref(dark_btn)
            ui.button('🚪', on_click=do_logout)\
                .props('flat round').classes('text-slate-400 dark:text-slate-500').tooltip('退出登录')

        # 全局键盘快捷键
        def _focus_input():
            """将焦点定位到聊天输入框"""
            js_code = """
            setTimeout(() => {
                const textareas = document.querySelectorAll('textarea');
                for (const ta of textareas) {
                    if (ta.placeholder && ta.placeholder.includes('描述您的遭遇')) {
                        ta.focus();
                        break;
                    }
                }
            }, 100);
            """
            ui.run_javascript(js_code)

        ui.keyboard(on_key=lambda e: _handle_global_key(e, _focus_input), ignore=[])

        # ════════════ 主体三栏：侧边栏（shrink-0）+ 聊天区（flex-1 min-w-[500px]）+ 表单（shrink-0）════════════
        with ui.row().classes('w-full flex-1 min-h-0 overflow-hidden overflow-x-hidden max-w-full').style('display: flex;'):
            # 左侧边栏：固定 260px，半透明微灰背景，无右侧边框
            with ui.column().classes('shrink-0 overflow-y-auto backdrop-blur-md bg-main-sidebar').style(
                'width: 260px; min-width: 260px; max-width: 260px; '
                'border-right: none; '
                'background: rgba(248,250,253,0.82);'
            ):
                build_sidebar_inline()

            # 中间聊天区：flex-1 弹性撑满 + 最小宽度 500px 防挤压
            with ui.column().classes('flex-1 min-w-[500px] h-full overflow-hidden backdrop-blur-sm bg-main-chat').style(
                'display: flex; flex-direction: column; '
                'background: rgba(255,255,255,0.75);'
            ):
                if state.main_subpage == "chat":
                    build_chat_area()
                elif state.main_subpage == "knowledge":
                    build_knowledge_page()

            # 右侧卷宗表单：仅在案件模式（PRO）下显示
            if state.ai_mode == "PRO":
                with ui.column().classes('shrink-0 overflow-y-auto backdrop-blur-md bg-main-panel').style(
                    'width: 380px; min-width: 380px; max-width: 380px; '
                    'border-left: none; '
                    'background: rgba(248,250,253,0.82);'
                ):
                    form_panel_area()


def do_logout():
    state.logged_in = False
    state.main_subpage = "chat"
    state.messages = []
    state.uploaded_files = []
    ui.navigate.to('/')

# ══════════════════════════════════════════
# 10. 侧边栏
# ══════════════════════════════════════════
def build_sidebar_inline():
    """侧边栏（内联版 — 直接用于 render_main 的 flex 布局）"""
    # 卷宗管理
    ui.label('🗂️ 卷宗管理').style(f'color:{COLOR_PRIMARY}').classes('text-sm font-bold px-4 pt-3 pb-1')

    tid = state.thread_id or f"case_{state.username}_{uuid.uuid4().hex[:6]}"
    state.thread_id = tid
    ui.label(f'案件编号: {tid}').classes('text-xs text-slate-400 dark:text-slate-500 px-4')

    ui.separator().style('margin: 4px 12px;')

    def clear_chat():
        state.messages = []
        state.form_data = {"案件发生地": "", "单位名称": "", "平均月薪": "", "时间节点": "", "核心诉求": "", "详细经过": ""}
        state.ready_for_analysis = False
        state.report_generated = False
        state.context_round_count = 0
        state.uploaded_files = []
        ui.notify('对话已清空', type='info')
        chat_messages_area.refresh()
        form_panel_area.refresh()

    def reset_case():
        state.messages = []
        state.form_data = {"案件发生地": "", "单位名称": "", "平均月薪": "", "时间节点": "", "核心诉求": "", "详细经过": ""}
        state.ready_for_analysis = False
        state.report_generated = False
        state.context_round_count = 0
        state.thread_id = f"case_{state.username}_{uuid.uuid4().hex[:6]}"
        state.uploaded_files = []
        ui.notify('已开启新案', type='info')
        chat_messages_area.refresh()
        form_panel_area.refresh()

    ui.button('🧹 清空当前屏幕对话', on_click=clear_chat).props('flat').classes('w-full justify-start px-4')
    ui.button('🔄 彻底重置并开启新案', on_click=reset_case).props('flat').classes('w-full justify-start px-4')

    ui.separator().style('margin: 8px 12px;')

    # 功能导航
    ui.label('📋 功能导航').style(f'color:{COLOR_PRIMARY}').classes('text-sm font-bold px-4 pt-1 pb-1')

    def go_chat():
        state.main_subpage = "chat"
        ui.navigate.to('/')

    def go_knowledge():
        state.main_subpage = "knowledge"
        ui.navigate.to('/')

    chat_active = '!bg-[#0F2C5C] !text-white' if state.main_subpage == "chat" else ''
    kb_active = '!bg-[#0F2C5C] !text-white' if state.main_subpage == "knowledge" else ''

    ui.button('💬 AI 咨询', on_click=go_chat).props('flat').classes(f'w-full justify-start px-4 {chat_active}')
    kb_btn = ui.button('🔧 知识库管理', on_click=go_knowledge).props('flat').classes(f'w-full justify-start px-4 {kb_active}')
    if state.user_role != "admin":
        kb_btn.props('disable')

    ui.separator().style('margin: 8px 12px;')

    # API 设置
    ui.label('🔑 API 设置').style(f'color:{COLOR_PRIMARY}').classes('text-sm font-bold px-4 pt-1 pb-1')

    api_config = get_user_api_config(state.username)
    current_provider = api_config.get("api_provider", "qwen")
    provider_names = {"qwen": "阿里云百炼", "deepseek": "DeepSeek", "siliconflow": "硅基流动", "custom": "自定义"}
    ui.label(f'当前: {provider_names.get(current_provider, current_provider)}')\
        .classes('text-xs text-slate-500 dark:text-slate-400 px-4')

    api_key_display = api_config.get("api_key", "")
    if api_key_display:
        masked = api_key_display[:8] + "****" + api_key_display[-4:] if len(api_key_display) > 12 else "****"
        ui.label(f'Key: {masked}').classes('text-xs text-slate-400 dark:text-slate-500 px-4')
    else:
        ui.label('⚠️ 未设置 API Key').classes('text-xs text-red-600 dark:text-red-400 px-4')

    ui.button('⚙️ 修改 API 配置', on_click=open_api_settings).props('flat').classes('w-full justify-start px-4')

    ui.separator().style('margin: 8px 12px;')

    # 用户管理（仅管理员）
    if state.user_role == "admin":
        ui.label('👥 用户管理 (管理员)').style(f'color:{COLOR_PRIMARY}').classes('text-sm font-bold px-4 pt-1 pb-1')

        users_data = load_users()
        ui.label(f'当前共 {len(users_data)} 个用户').classes('text-xs text-slate-500 dark:text-slate-400 px-4')

        for uname, udata in users_data.items():
            with ui.row().classes('w-full items-center px-4 py-0.5'):
                role_icon = '🔒' if udata.get("role") == "admin" else "👤"
                ui.label(f'{role_icon} {uname} ({udata.get("name", "")})').classes('text-xs text-slate-700 dark:text-slate-300')
                ui.space()
                if uname != "lzy" and uname != state.username:
                    def make_delete(u):
                        return lambda: do_delete_user(u)
                    ui.button('🗑️', on_click=make_delete(uname)).props('flat dense size=sm').classes('text-red-600')

    ui.space()


def do_delete_user(uname):
    delete_user(uname)
    ui.notify(f'用户 {uname} 已删除', type='warning')
    ui.navigate.to('/')


def open_api_settings():
    api_config = get_user_api_config(state.username)

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg'):
        ui.label('⚙️ 修改 API 配置').style(f'font-size:18px; font-weight:bold; color:{COLOR_PRIMARY}')
        ui.label('数据仅存储在本地，不会上传到任何服务器').classes('text-xs text-slate-500')

        ui.separator()

        provider_var = ui.select(
            label='API 平台',
            options={v: t for t, v in API_PROVIDER_OPTIONS},
            value=api_config.get("api_provider", "qwen")
        ).classes('w-full').props('outlined')

        key_input = ui.input('API Key *', value=api_config.get("api_key", ""))\
            .classes('w-full').props('outlined type=password')
        url_input = ui.input('Base URL', value=api_config.get("base_url", ""))\
            .classes('w-full').props('outlined')
        model_input = ui.input('模型名称', value=api_config.get("model", ""))\
            .classes('w-full').props('outlined')

        def on_provider_change():
            p = provider_var.value
            defaults = API_PROVIDER_DEFAULTS.get(p, {})
            url_input.value = defaults.get("base_url", "")
            model_input.value = defaults.get("model", "")
        provider_var.on('update:model-value', on_provider_change)

        status_label = ui.label('').classes('text-xs')

        def save_api():
            key = (key_input.value or '').strip()
            provider = provider_var.value
            url = (url_input.value or '').strip()
            model = (model_input.value or '').strip()

            if not key:
                status_label.set_text('API Key 不能为空')
                status_label.classes('text-red-600')
                return
            if len(key) < 8:
                status_label.set_text('API Key 格式不正确')
                status_label.classes('text-red-600')
                return

            update_user_api(state.username, key, provider, url, model)
            global _backend_cache
            if state.username in _backend_cache:
                del _backend_cache[state.username]
            ui.notify('API 配置已保存！重新进入 AI 咨询将使用新配置', type='positive')
            dialog.close()
            ui.navigate.to('/')

        with ui.row().classes('gap-2 justify-end'):
            ui.button('取消', on_click=dialog.close).props('outline')
            ui.button('💾 保存配置', on_click=save_api).props('color=primary')

    dialog.open()

# ══════════════════════════════════════════
# 11. 聊天区域 — 使用 @ui.refreshable + ui.chat_message
# ══════════════════════════════════════════
def build_chat_area():
    """AI 咨询聊天页面 — Gemini 极简风格"""
    # 聊天区已是 flex-1 撑满，直接嵌入 build_chat_panel
    build_chat_panel()


@ui.refreshable
def chat_messages_area():
    """局部可刷新的消息列表 — Gemini 极简空状态 + 气泡质感升级"""
    if state.report_generated:
        ui.chat_message(
            '✅ 深度分析已完成！出于隐私保护，对话记录已自动焚毁。',
            name='系统', sent=False, avatar='✅'
        ).classes('bg-emerald-50 dark:bg-emerald-900/30 text-slate-700 dark:text-slate-200')\
         .style('overflow-wrap: break-word; word-break: break-word;')
        if state.analysis_result:
            advice = state.analysis_result.get("final_review", state.analysis_result.get("content", ""))
            ui.chat_message(
                advice[:5000] if advice else '报告内容为空',
                name='📄 分析报告', sent=False, avatar='📄'
            ).classes('bg-slate-100 dark:bg-zinc-800 text-slate-800 dark:text-slate-200')\
             .style('overflow-wrap: break-word; word-break: break-word;')
    elif not state.messages:
        # ════════════ Gemini 风格空状态欢迎页 ════════════
        with ui.column().classes('items-center justify-center w-full h-full')\
            .style('min-height: 450px;'):
            # 极简问候语
            ui.label(f'你好，{state.user_name}')\
                .classes('text-3xl font-medium text-slate-800 dark:text-slate-200 mb-6')
            ui.label('今天有什么劳动法问题需要我帮助？')\
                .classes('text-base text-slate-400 dark:text-slate-500 mb-10')

            # ── 流式换行的引导提示词 Chips ──
            quick_questions = [
                ("💡", "如何计算违法解除赔偿金？"),
                ("📋", "试用期被辞退怎么办？"),
                ("📎", "收集哪些证据可以证明劳动关系？"),
                ("💰", "加班费的计算标准是什么？"),
                ("📝", "没有签劳动合同怎么维权？"),
                ("⚖️", "工伤认定的流程和时限？"),
            ]
            with ui.row().classes('flex-wrap justify-center gap-3 w-full max-w-2xl px-4'):
                for icon, question in quick_questions:
                    btn = ui.button(f'{icon}  {question}', on_click=lambda q=question: _quick_send(q))\
                        .props('flat no-caps').classes(
                            'rounded-full '
                            'bg-white dark:bg-zinc-800 '
                            'border border-slate-200 dark:border-zinc-700 '
                            'px-5 py-2 text-sm text-slate-700 dark:text-slate-300 '
                            'hover:bg-slate-50 dark:hover:bg-zinc-700 cursor-pointer '
                            'transition-colors'
                        )
    else:
        # ════════════ 聊天气泡列表 ════════════
        for msg_idx, msg in enumerate(state.messages):
            if msg["role"] == "user":
                # 用户消息：无头像，柔和微灰大圆角气泡
                ui.chat_message(
                    msg["content"],
                    name=state.user_name or '我', sent=True, avatar=USER_AVATAR_URL
                ).classes(
                    'max-w-[80%] ml-auto '
                    'rounded-3xl px-6 py-3 '
                    'bg-slate-100 dark:bg-zinc-800 '
                    'text-slate-800 dark:text-slate-200'
                ).style(
                    'overflow-wrap: break-word; word-break: break-word;'
                )
            else:
                content = msg.get("content", "")
                citations = msg.get("citations", {})
                if citations:
                    _render_citation_content(content, citations)
                else:
                    # AI 消息：完全透明背景，✨ 发光图标，文字直接铺在页面上
                    ui.chat_message(
                        content,
                        name='AI 劳动法助手', sent=False, avatar=AI_AVATAR_URL
                    ).classes(
                        'max-w-[85%] bg-transparent '
                        'leading-relaxed text-base '
                        'text-slate-800 dark:text-slate-200'
                    ).style(
                        'overflow-wrap: break-word; word-break: break-word;'
                    )
                # 审计轨迹
                trail = msg.get("audit_trail", [])
                if trail:
                    _render_audit_trail(trail)
                # 引用来源面板
                if citations:
                    _render_citation_panel(citations)
                # 反馈按钮
                if content and '正在思考' not in content and '正在生成' not in content:
                    _render_feedback_buttons(msg_idx, content, citations)


def _render_citation_content(content: str, citations: dict):
    """将带 [1][2] 标记的文本渲染为 ui.chat_message + 可点击引用上标"""
    # 用正则分割：匹配 [数字] 或 [数字,数字]
    parts = re.split(r'(\[\d+(?:,\d+)*\])', content)

    # 先用 chat_message 渲染纯文本框架，然后在下方追加引用按钮行
    with ui.chat_message(name='AI 劳动法助手', sent=False, avatar=AI_AVATAR_URL)\
        .classes('max-w-[85%] bg-transparent leading-relaxed text-base text-slate-800 dark:text-slate-200')\
        .style('overflow-wrap: break-word; word-break: break-word;'):
        # 构建一个 row 来逐段渲染文本和引用上标
        with ui.element('div').classes('text-sm leading-relaxed whitespace-pre-wrap'):
            current_text = ""
            for part in parts:
                m = re.match(r'\[(\d+(?:,\d+)*)\]', part)
                if m:
                    # 先输出之前累积的文本
                    if current_text:
                        ui.label(current_text).classes('inline')
                        current_text = ""
                    # 渲染引用上标按钮
                    ref_ids = m.group(1).split(',')
                    for rid in ref_ids:
                        rid = rid.strip()
                        if rid in citations:
                            cit = citations[rid]
                            tooltip = f"{cit.get('source','')} {cit.get('article','')}"
                            btn = ui.button(f'[{rid}]', on_click=lambda c=cit: _show_citation_dialog(c))\
                                .props(f'flat dense size=sm no-caps').classes('text-blue-600 text-xs font-bold mx-0.5')
                            btn.tooltip(tooltip[:80])
                else:
                    current_text += part
            # 输出剩余文本
            if current_text:
                ui.label(current_text).classes('inline')


def _show_citation_dialog(citation: dict):
    """弹出引用原文对话框"""
    source = citation.get("source", "未知来源")
    article = citation.get("article", "")
    text = citation.get("text", "")
    title = f"《{source}》" + (f" {article}" if article else "")
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
        ui.label('📖 引用来源').classes('text-lg font-bold').style(f'color:{COLOR_PRIMARY}')
        ui.label(title).classes('text-base font-medium text-slate-700 mt-1')
        ui.separator()
        ui.label('📜 原文摘录').classes('text-xs font-bold text-slate-500')
        with ui.scroll_area().classes('max-h-96'):
            ui.label(text).classes('text-sm whitespace-pre-wrap leading-relaxed')
        ui.separator()
        ui.label('⚠️ 以上内容由 RAG 知识库检索，仅供参考，请以官方发布的法律文本为准。')\
            .classes('text-xs text-amber-600')
        with ui.row().classes('justify-end'):
            ui.button('关闭', on_click=dialog.close).props('flat')
    dialog.open()


def _render_citation_panel(citations: dict):
    """在消息下方渲染引用来源折叠面板"""
    with ui.expansion(f'📎 引用来源（{len(citations)} 条）').classes('w-full bg-blue-50 dark:bg-blue-900/20 text-slate-600 dark:text-slate-300 text-xs mt-2'):
        with ui.column().classes('gap-2 py-1'):
            for ref_id in sorted(citations.keys(), key=int):
                cit = citations[ref_id]
                source = cit.get("source", "未知来源")
                article = cit.get("article", "")
                title = f"《{source}》" + (f" {article}" if article else "")
                with ui.row().classes('items-start gap-2'):
                    ui.label(f'[{ref_id}]').classes('text-blue-600 font-bold text-xs min-w-[24px]')
                    with ui.column().classes('gap-0'):
                        ui.label(title).classes('text-xs font-medium text-slate-700')
                        # 可点击查看详情
                        ui.button('📖 查看原文', on_click=lambda c=cit: _show_citation_dialog(c))\
                            .props('flat dense size=sm no-caps').classes('text-blue-500 text-xs')


def _render_audit_trail(trail: list):
    """在 assistant 消息下方渲染审计轨迹折叠面板"""
    with ui.expansion('⚙️ 多智能体推演轨迹').classes('w-full bg-slate-50 dark:bg-zinc-800 text-slate-500 dark:text-slate-400 text-xs mt-2'):
        with ui.column().classes('gap-1 py-1'):
            for i, step in enumerate(trail):
                # 判断当前步骤状态：最后一个条目可能正在运行中
                is_last = (i == len(trail) - 1)
                is_streaming = state._is_streaming and is_last
                icon = '⏳' if is_streaming else '✅'
                text_class = 'text-slate-700 font-medium' if is_streaming else 'text-slate-500'
                with ui.row().classes('items-center gap-2'):
                    ui.label(icon).classes('text-xs')
                    ui.label(step).classes(f'text-xs {text_class}')
                    if is_streaming:
                        ui.spinner('dots', size='1em')


# ── 反馈系统 UI ──
def _render_feedback_buttons(msg_idx: int, ai_content: str, citations: dict):
    """在 AI 消息底部渲染 👍/👎 反馈按钮"""
    # 使用 msg_idx 作为唯一标识，防止重复反馈
    feedback_key = f"feedback_{msg_idx}"
    
    with ui.row().classes('gap-1 mt-1 pl-2'):
        # 👍 正向反馈按钮
        pos_btn = ui.button(icon='thumb_up', on_click=lambda k=feedback_key: _on_positive_feedback(k))\
            .props('flat dense size=sm round').classes('text-slate-400 dark:text-slate-500')
        pos_btn.tooltip('回答有帮助')
        
        # 👎 负向反馈按钮
        neg_btn = ui.button(icon='thumb_down', on_click=lambda k=feedback_key, c=ai_content, ct=citations: _on_negative_feedback(k, c, ct))\
            .props('flat dense size=sm round').classes('text-slate-400 dark:text-slate-500')
        neg_btn.tooltip('回答有误或不完整')


# 记录已反馈的消息 ID（防止重复提交）
_feedback_submitted = set()

def _on_positive_feedback(feedback_key: str):
    """正向反馈处理"""
    if feedback_key in _feedback_submitted:
        return
    _feedback_submitted.add(feedback_key)
    
    # 从 feedback_key 解析消息索引（格式：feedback_<msg_idx>）
    try:
        msg_idx = int(feedback_key.rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        msg_idx = -1
    
    # 找到该 AI 回复对应的用户提问（其前一条 user 消息）
    user_query = ""
    if 0 <= msg_idx < len(state.messages):
        # 向前查找最近的 user 消息
        for j in range(msg_idx - 1, -1, -1):
            if state.messages[j]["role"] == "user":
                user_query = state.messages[j]["content"]
                break
    
    ai_response = ""
    if 0 <= msg_idx < len(state.messages):
        ai_response = state.messages[msg_idx].get("content", "")
    
    save_user_feedback(
        feedback_type="positive",
        thread_id=state.thread_id,
        user_query=user_query,
        ai_response=ai_response,
        citations=state.messages[msg_idx].get("citations", {}) if 0 <= msg_idx < len(state.messages) else {},
    )
    ui.notify('👍 感谢反馈！您的评价将帮助我们改进服务', type='positive')


def _on_negative_feedback(feedback_key: str, ai_content: str, citations: dict):
    """负向反馈处理：弹出纠错对话框"""
    if feedback_key in _feedback_submitted:
        return
    _feedback_submitted.add(feedback_key)
    
    # 从 feedback_key 解析消息索引（格式：feedback_<msg_idx>）
    try:
        msg_idx = int(feedback_key.rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        msg_idx = -1
    
    # 找到该 AI 回复对应的用户提问
    user_query = ""
    if 0 <= msg_idx < len(state.messages):
        for j in range(msg_idx - 1, -1, -1):
            if state.messages[j]["role"] == "user":
                user_query = state.messages[j]["content"]
                break
    
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg'):
        ui.label('📝 请告诉我们哪里出了问题').classes('text-lg font-bold').style(f'color:{COLOR_PRIMARY}')
        ui.label('您的纠正意见将帮助 AI 持续改进，感谢您的贡献！').classes('text-xs text-slate-500 dark:text-slate-400')
        ui.separator()
        
        correction_input = ui.textarea(
            label='您的纠正意见或预期结果',
            placeholder='例如：法条引用有误，应引用《劳动合同法》第XX条...'
        ).classes('w-full').props('outlined rows=3 autogrow')
        
        status_label = ui.label('').classes('text-xs')
        
        def submit_correction():
            correction_text = (correction_input.value or '').strip()
            if not correction_text:
                status_label.set_text('请输入您的纠正意见')
                status_label.classes('text-red-600')
                return
            
            save_user_feedback(
                feedback_type="negative",
                thread_id=state.thread_id,
                user_query=user_query,
                ai_response=ai_content,
                citations=citations,
                correction=correction_text,
            )
            dialog.close()
            ui.notify('👎 感谢您的纠正！我们会持续优化 AI 表现', type='info')
        
        with ui.row().classes('gap-2 justify-end'):
            ui.button('取消', on_click=lambda: (dialog.close(), _feedback_submitted.discard(feedback_key))).props('flat')
            ui.button('提交反馈', on_click=submit_correction).props('color=primary')
    
    dialog.open()


# ── 快捷引导问：全局引用，供空状态标签点击后填入并发送 ──
_quick_input_ref = None
_quick_send_ref = None

def _set_input_refs(input_box, send_fn):
    """保存输入框和发送函数的引用，供快捷引导问使用"""
    global _quick_input_ref, _quick_send_ref
    _quick_input_ref = input_box
    _quick_send_ref = send_fn

async def _quick_send(text: str):
    """快捷引导问：填入输入框并触发发送"""
    global _quick_input_ref, _quick_send_ref
    if _quick_input_ref is not None and _quick_send_ref is not None:
        _quick_input_ref.value = text
        await _quick_send_ref()


def build_chat_panel():
    """聊天面板：消息滚动区 + Gemini 风格悬浮大圆角 Composer"""
    # ════════════ 1. 消息滚动区 — 无边框沉浸式 ════════════
    chat_scroll = ui.scroll_area().props('dark').style(
        'flex: 1 1 1px; min-height: 200px; '
        'padding: 0 20px;'
    )

    with chat_scroll:
        chat_messages_area()

    # JS：确保 scroll_area 高度正确 + 自动滚到底部
    ui.run_javascript("""
        setTimeout(function() {
            var scrollAreas = document.querySelectorAll('.q-scrollarea');
            scrollAreas.forEach(function(sa) {
                sa.style.flex = '1 1 1px';
                sa.style.minHeight = '200px';
            });
            var containers = document.querySelectorAll('.q-scrollarea__container');
            containers.forEach(function(c) { c.style.height = '100%'; });
            var contents = document.querySelectorAll('.q-scrollarea__content');
            contents.forEach(function(c) { c.style.minHeight = '100%'; });
            scrollAreas.forEach(function(sa) {
                var container = sa.querySelector('.q-scrollarea__container');
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        }, 200);
    """)

    # ════════════ 2. Gemini 风格悬浮大圆角 Composer ════════════
    with ui.element('div').style(
        'flex-shrink: 0; margin: 8px auto 20px auto; width: 100%; max-width: 768px;'
    ):
        # ── 外层悬浮大药丸容器 ──
        with ui.element('div').classes(
            'w-full max-w-4xl mx-auto '
            'bg-white dark:bg-zinc-800 '
            'rounded-[32px] shadow-sm '
            'border border-slate-200 dark:border-zinc-700 '
            'px-4 py-2 flex flex-row items-end gap-2 mb-6'
        ):
            # ── 左侧操作区：极简模式切换 + 附件上传 ──
            mode_label_text = '⚡ Quick' if state.ai_mode == 'QUICK' else '💼 Pro'

            def apply_mode(mode: str, button=None):
                was_unconfirmed = not state.ai_mode_confirmed
                state.ai_mode = mode
                state.ai_mode_confirmed = True
                state.ready_for_analysis = False
                state.report_generated = False
                if button is not None:
                    button.set_text('⚡ Quick' if mode == 'QUICK' else '💼 Pro')
                ui.notify('已切换到普法模式' if mode == 'QUICK' else '已切换到案件模式', type='info')
                chat_messages_area.refresh()
                form_panel_area.refresh()
                if was_unconfirmed:
                    ui.navigate.to('/')

            def toggle_mode():
                apply_mode('PRO' if state.ai_mode == 'QUICK' else 'QUICK', mode_btn)

            mode_btn = ui.button(mode_label_text, on_click=toggle_mode if state.ai_mode_confirmed else None)\
                .props('flat dense no-caps').classes(
                    'text-slate-500 hover:bg-slate-100 '
                    'dark:hover:bg-zinc-700 '
                    'rounded-full px-3 py-2 transition-colors '
                    'self-center'
                )

            if not state.ai_mode_confirmed:
                with ui.menu():
                    ui.menu_item('⚡ 普法模式 Quick', on_click=lambda: apply_mode('QUICK', mode_btn))
                    ui.menu_item('💼 案件模式 Pro', on_click=lambda: apply_mode('PRO', mode_btn))

            # ── 附件上传按钮 → 弹出上传对话框 ──
            def open_upload_dialog():
                with ui.dialog() as upload_dialog, ui.card().classes('w-full max-w-md'):
                    ui.label('📎 上传文件').classes('text-lg font-bold').style(f'color:{COLOR_PRIMARY}')
                    ui.label('支持上传劳动合同、证据材料等文件（PDF/Word/图片/文本）')\
                        .classes('text-xs text-slate-500 dark:text-slate-400 mb-3')

                    def handle_upload(e):
                        if e and e.content:
                            file_data = e.content.read()
                            file_name = e.name or '未命名文件'
                            file_size = len(file_data)
                            state.uploaded_files.append({
                                "name": file_name,
                                "size": file_size,
                            })
                            ui.notify(f'✅ {file_name} 上传成功（{file_size/1024:.1f} KB）', type='positive')
                            chat_messages_area.refresh()

                    ui.upload(
                        on_upload=handle_upload,
                        multiple=True,
                        label='拖拽或点击上传劳动合同/证据文件'
                    ).classes('w-full').props('accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png,.webp" max-file-size=20971520')

                    ui.separator()

                    with ui.row().classes('gap-2 justify-end'):
                        ui.button('完成', on_click=upload_dialog.close).props('color=primary')

                upload_dialog.open()

            ui.button(icon='attach_file', on_click=open_upload_dialog)\
                .props('flat round dense size=sm')\
                .classes('text-slate-500 hover:bg-slate-100 '
                         'dark:hover:bg-zinc-700 '
                         'rounded-full px-2 py-2 transition-colors '
                         'self-center')\
                .tooltip('上传文件')

            # ── 输入区域：borderless 透明背景 + 已上传文件标签 ──
            with ui.column().classes('flex-1 min-w-0 gap-1'):
                # 已上传文件标签行
                if state.uploaded_files:
                    with ui.row().classes('flex-wrap gap-1'):
                        for idx, f in enumerate(state.uploaded_files):
                            fname = f.get("name", "")
                            fsize = f.get("size", 0)
                            size_str = f'{fsize/1024:.1f}KB' if fsize < 1024*1024 else f'{fsize/1024/1024:.1f}MB'

                            def make_remove(filename, filesize):
                                def remove_file():
                                    # 使用文件名+大小匹配而非索引，避免连续移除时索引漂移
                                    target = None
                                    for item in state.uploaded_files:
                                        if item.get("name") == filename and item.get("size") == filesize:
                                            target = item
                                            break
                                    if target:
                                        state.uploaded_files.remove(target)
                                        ui.notify(f'已移除 {target.get("name","")}', type='info')
                                        chat_messages_area.refresh()
                                return remove_file

                            ui.chip(f'📎 {fname} ({size_str})', removable=True, on_remove=make_remove(fname, fsize))\
                                .classes('text-xs bg-blue-50 dark:bg-blue-900/20 text-slate-700 dark:text-slate-300')\
                                .props('dense size=sm')

                input_box = ui.textarea(
                    placeholder='描述您的遭遇或提出疑问...'
                ).classes('flex-1 mx-2 bg-transparent text-slate-800 dark:text-slate-200').props(
                    'borderless autogrow inputmode=text lang=zh-CN autocomplete=off autocorrect=off autocapitalize=off spellcheck=false'
                ).style(
                    'min-height: 44px; font-size: 15px; '
                    'padding-top: 10px; padding-bottom: 10px;'
                )

            async def do_send():
                msg = (input_box.value or '').strip()
                if not msg:
                    return
                input_box.value = ''
                await send_message(msg)

            async def send_on_enter():
                await do_send()

            # 注册全局引用（供快捷引导问使用）
            _set_input_refs(input_box, do_send)

            input_box.on(
                'keydown',
                send_on_enter,
                js_handler="""(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        event.stopPropagation();
                        emit();
                    }
                }""",
            )

            # ── 发送按钮：圆形极简图标按钮 ──
            ui.button(icon='arrow_upward', on_click=do_send)\
                .props('round flat size=sm')\
                .classes('bg-blue-50 dark:bg-blue-900/30 '
                         'text-blue-600 dark:text-blue-400 '
                         'mb-1 self-center')


# ══════════════════════════════════════════
# 12. 异步 send_message — 替代线程+队列轮询
# ══════════════════════════════════════════
async def send_message(msg: str):
    """异步发送用户消息并调用后端，逐节点实时刷新审计轨迹 UI"""
    if state._is_streaming:
        ui.notify('AI 正在思考中，请稍候', type='warning')
        return

    # 如果有上传的文件，将文件信息附加到消息中
    if state.uploaded_files:
        file_names = [f.get("name", "未命名文件") for f in state.uploaded_files]
        msg = msg + "\n\n[已上传文件: " + ", ".join(file_names) + "]"
        state.uploaded_files = []  # 发送后清空文件列表

    state.messages.append({"role": "user", "content": msg})
    chat_messages_area.refresh()

    if not state._app:
        state._app, state._llm, state._llm_fast, state._embeddings = load_backend(state.username)
        if not state._app:
            state.messages.append({"role": "assistant", "content": "⚠️ 后端未加载，请先在左侧「API 设置」中配置您的 API Key。"})
            chat_messages_area.refresh()
            return

    state._is_streaming = True

    # 占位消息（含空 audit_trail）
    state.messages.append({"role": "assistant", "content": "⏳ AI 正在思考...", "audit_trail": []})
    chat_messages_area.refresh()

    try:
        from langchain_core.messages import HumanMessage

        config = {"configurable": {"thread_id": state.thread_id}}
        prompt = msg
        if state.ai_mode == "PRO":
            form_str = "\n".join([f"{k}: {v}" for k, v in state.form_data.items() if v])
            if form_str:
                prompt = f"【已提取的案件信息】\n{form_str}\n\n【用户问题】\n{msg}"

        backend_msg = HumanMessage(content=prompt)

        # ── 审计轨迹：用 stream_mode="updates" 获取节点名，逐步消费 ──
        global _stream_iter

        def _init_stream():
            global _stream_iter
            _stream_iter = state._app.stream(
                {"messages": [backend_msg]}, config, stream_mode="updates"
            )
            return True

        def _get_next_update():
            """从全局迭代器中取下一个节点更新；返回 (node_name, content) 或 None"""
            global _stream_iter
            if _stream_iter is None:
                return None
            while True:
                try:
                    update = next(_stream_iter)
                except StopIteration:
                    _stream_iter = None
                    return None
                except Exception:
                    _stream_iter = None
                    return None

                if not update:
                    continue

                # update 格式: {node_name: {state_keys: values}}；部分节点可能返回 None。
                node_name = list(update.keys())[0]
                node_data = update[node_name] or {}
                if not isinstance(node_data, dict):
                    return (node_name, "")

                content_parts = []
                triage_reply = node_data.get("triage_result", {}).get("reply")
                if triage_reply:
                    content_parts.append(triage_reply)

                msgs = node_data.get("messages", [])
                for m in msgs:
                    if hasattr(m, 'content') and m.content:
                        if m.content not in content_parts:
                            content_parts.append(m.content)
                return (node_name, "".join(content_parts))

        # 初始化迭代器
        await run.io_bound(_init_stream)

        all_contents = []
        audit_trail = []
        all_citations = {}  # 收集 RAG 溯源引用

        while True:
            result = await run.io_bound(_get_next_update)
            if result is None:
                break
            node_name, node_content = result
            friendly = NODE_FRIENDLY_NAMES.get(node_name, f"⚙️ {node_name}")
            audit_trail.append(friendly)
            if node_content:
                all_contents.append(node_content)
            # 实时更新占位消息的 audit_trail
            state.messages[-1] = {
                "role": "assistant",
                "content": "⏳ AI 正在思考...",
                "audit_trail": list(audit_trail),
            }
            chat_messages_area.refresh()

        full_response = "".join(all_contents)

        # ── 提取 RAG 溯源引用：从 final state 中获取 relevant_sources ──
        def _get_citations():
            """从 LangGraph state 中提取 relevant_sources 并构建 citations"""
            try:
                final_state = state._app.get_state(config)
                state_values = final_state.values if hasattr(final_state, 'values') else {}
                sources = state_values.get("relevant_sources", [])
                if sources:
                    return {s["id"]: {"source": s["source"], "article": s["article"], "text": s["text"]} for s in sources}
            except Exception:
                pass
            return {}

        all_citations = await run.io_bound(_get_citations)

        if full_response.strip():
            # 最终消息：完整内容 + 完整审计轨迹 + 引用溯源
            state.messages[-1] = {
                "role": "assistant",
                "content": full_response.strip(),
                "audit_trail": list(audit_trail),
                "citations": all_citations,
            }
        else:
            state.messages[-1] = {"role": "assistant", "content": "⚠️ 未获取到有效回复，请重试。"}

        # 案件模式：自动提取表单信息
        if state.ai_mode == "PRO":
            state.context_round_count += 1
            try:
                from langchain_core.messages import HumanMessage as HM, SystemMessage
                current_data = dict(state.form_data)
                chat_history_for_extract = [HM(content=m["content"]) for m in state.messages if m["role"] == "user"]
                if chat_history_for_extract:
                    extract_prompt = f"""你是一个后台数据提取器。请从【用户消息】中提取关键信息并更新【当前数据】。
没提到的保持空字符串 ""。

【当前数据】：{json.dumps(current_data, ensure_ascii=False)}
【用户消息】：{[m.content for m in chat_history_for_extract[-3:]]}
请严格返回包含这6个键的JSON："案件发生地", "单位名称", "平均月薪", "时间节点", "核心诉求", "详细经过"。"""

                    def _sync_extract():
                        return state._llm_fast.invoke([SystemMessage(content="只输出合法JSON"), HM(content=extract_prompt)])

                    response = await run.io_bound(_sync_extract)
                    clean = response.content.replace('```json', '').replace('```', '').strip()
                    new_data = json.loads(clean)
                    state.form_data = {k: new_data.get(k) if new_data.get(k) else current_data.get(k, "") for k in current_data.keys()}
            except Exception:
                pass

            pct, _, _ = evaluate_form_completeness(state.form_data)
            state.ready_for_analysis = pct >= 60 or state.context_round_count >= 10

    except Exception as e:
        import traceback
        traceback.print_exc()
        state.messages[-1] = {"role": "assistant", "content": f"❌ 错误: {e}"}

    finally:
        state._is_streaming = False

    chat_messages_area.refresh()
    form_panel_area.refresh()


# ══════════════════════════════════════════
# 13. 异步 generate_report — 替代线程+队列轮询
# ══════════════════════════════════════════
async def generate_report():
    """异步生成法律分析报告 — 含审计轨迹可视化"""
    if state._is_streaming:
        return
    if not state._app:
        state._app, state._llm, state._llm_fast, state._embeddings = load_backend(state.username)
        if not state._app:
            ui.notify('后端未加载，请检查 API 配置', type='negative')
            return

    state._is_streaming = True
    ui.notify('🔍 正在生成法律分析报告...', type='ongoing')

    # 在消息列表中追加一条占位消息用于显示审计轨迹
    state.messages.append({"role": "assistant", "content": "🔍 正在生成法律分析报告...", "audit_trail": []})
    chat_messages_area.refresh()

    try:
        from langchain_core.messages import HumanMessage

        final_form = dict(state.form_data)
        case_msg = HumanMessage(content="请分析以下劳动法案件：\n" + "\n".join([f"{k}：{v}" for k, v in final_form.items() if v]))
        new_thread = state.thread_id + "_direct"
        active_config = {"configurable": {"thread_id": new_thread}}

        audit_trail = []

        # ── 阶段 1：初始化（summarizer + triage） ──
        def _init_and_triage():
            init_result = state._app.invoke({"messages": [case_msg], "form_data": final_form}, active_config)
            triage_res = init_result.get("triage_result", {}) if isinstance(init_result, dict) else {}
            if triage_res.get("action") != "form":
                state._app.update_state(active_config, {"triage_result": {"action": "form", "category": "强制案件分析", "reply": "开始分析"}})
            state._app.update_state(active_config, {"form_data": final_form})
            return True

        await run.io_bound(_init_and_triage)
        audit_trail.extend([
            NODE_FRIENDLY_NAMES.get("summarizer", "📝 记忆压缩"),
            NODE_FRIENDLY_NAMES.get("triage", "🔍 分诊台"),
        ])
        state.messages[-1] = {"role": "assistant", "content": "🔍 正在生成法律分析报告...", "audit_trail": list(audit_trail)}
        chat_messages_area.refresh()

        # ── 阶段 2：流水线节点（fact_summarizer → legal_researcher → compliance_reviewer → quality_inspector） ──
        global _stream_iter

        def _init_report_stream():
            global _stream_iter
            _stream_iter = state._app.stream(None, active_config)
            return True

        def _get_next_report_update():
            global _stream_iter
            if _stream_iter is None:
                return None
            try:
                update = next(_stream_iter)
                node_name = list(update.keys())[0]
                return node_name
            except StopIteration:
                _stream_iter = None
                return None
            except Exception:
                _stream_iter = None
                return None

        await run.io_bound(_init_report_stream)

        while True:
            node_name = await run.io_bound(_get_next_report_update)
            if node_name is None:
                break
            friendly = NODE_FRIENDLY_NAMES.get(node_name, f"⚙️ {node_name}")
            audit_trail.append(friendly)
            state.messages[-1] = {"role": "assistant", "content": "🔍 正在生成法律分析报告...", "audit_trail": list(audit_trail)}
            chat_messages_area.refresh()

        # ── 阶段 3：提取最终结果 ──
        def _get_final_state():
            final_state = state._app.get_state(active_config)
            state_values = final_state.values if hasattr(final_state, 'values') else {}
            sources = state_values.get("relevant_sources", [])
            citations = {}
            if sources:
                citations = {s["id"]: {"source": s["source"], "article": s["article"], "text": s["text"]} for s in sources}
            return {
                "legal_facts_summary": state_values.get("legal_facts_summary", ""),
                "relevant_laws": state_values.get("relevant_laws", ""),
                "final_review": state_values.get("final_review", ""),
                "citations": citations,
            }

        analysis = await run.io_bound(_get_final_state)

        # 标记最后一条 audit_trail 消息完成（含 citations）
        report_citations = analysis.pop("citations", {})
        if state.messages:
            state.messages[-1] = {
                "role": "assistant",
                "content": "✅ 法律分析报告已生成，请在右侧卷宗面板查看。",
                "audit_trail": list(audit_trail),
                "citations": report_citations,
            }

        state.analysis_result = analysis
        state.report_generated = True
        state.ready_for_analysis = False
        ui.notify('✅ 报告生成完成！', type='positive')

    except Exception as e:
        import traceback
        traceback.print_exc()
        state.messages[-1] = {"role": "assistant", "content": f"❌ 错误: {e}"}
        ui.notify(f'❌ 错误: {e}', type='negative')

    finally:
        state._is_streaming = False

    chat_messages_area.refresh()
    form_panel_area.refresh()


# ══════════════════════════════════════════
# 14. 右侧智能案件卷宗面板 — @ui.refreshable
# ══════════════════════════════════════════
@ui.refreshable
def form_panel_area():
    """右侧案件卷宗表单"""
    with ui.card().classes('w-full h-full backdrop-blur-sm overflow-y-auto text-slate-800 dark:text-slate-200 bg-main-card')\
        .style(
            f'display: flex; flex-direction: column; '
            f'border:1px solid {COLOR_BORDER}; border-radius: 12px; '
            'background: rgba(255,255,255,0.82);'
        ):
        # 标题区
        with ui.row().classes('w-full items-center justify-between px-4 pt-4 pb-2'):
            ui.label('📑 智能案件卷宗').style(f'font-size:15px; font-weight:700; color:{COLOR_PRIMARY}').classes('dark:text-slate-100')

        # 信息完善度
        pct, _, suggestion = evaluate_form_completeness(state.form_data)
        bar_color = 'green' if pct >= 60 else ('amber' if pct >= 30 else 'red')
        with ui.row().classes('w-full px-4 items-center gap-2'):
            ui.label(f'完善度 {pct}%')\
                .classes(f'text-xs font-bold text-{bar_color}-600 dark:text-{bar_color}-400')
            ui.linear_progress(value=pct / 100, color=bar_color)\
                .props('instant-feedback size=sm').classes('flex-1')

        # 表单字段
        fields = [
            ("案件发生地", "例如：广东省深圳市"),
            ("单位名称", "例如：XX科技有限公司"),
            ("平均月薪", "例如：8000"),
            ("时间节点", "例如：2023年3月入职"),
            ("核心诉求", "例如：要求支付违法解除赔偿金"),
        ]
        for label, placeholder in fields:
            val = state.form_data.get(label, "")
            inp = ui.input(label=label, placeholder=placeholder, value=val)\
                .classes('w-full').props('outlined dense')
            def make_handler(k, i=inp):
                def handler():
                    state.form_data[k] = (i.value or '').strip()
                return handler
            inp.on('update:model-value', make_handler(label))

        detail_val = state.form_data.get("详细经过", "")
        detail_input = ui.textarea(label='详细经过', value=detail_val)\
            .classes('w-full').props('outlined rows=4')
        def detail_handler():
            state.form_data["详细经过"] = (detail_input.value or '').strip()
        detail_input.on('update:model-value', detail_handler)

        # 状态提示
        if state.ready_for_analysis:
            ui.label('✅ AI 认为信息已充足，请核对并生成报告。').classes('text-sm text-green-600')
            report_enabled = True
            report_text = '✅ 生成法律分析报告'
        elif pct == 0:
            ui.label('👋 请在左侧向我描述您的案情，我会自动为您提取并填写此处信息。')\
                .classes('text-xs text-slate-500 dark:text-slate-400')
            report_enabled = False
            report_text = '🔍 生成法律分析报告'
        else:
            color_class = 'text-amber-600 dark:text-amber-400' if pct < 60 else 'text-blue-600 dark:text-blue-400'
            ui.label(f'📊 {suggestion}').classes(f'text-xs {color_class}')
            report_enabled = pct >= 40
            report_text = '🔍 生成法律分析报告' if pct >= 40 else '🔍 强制生成报告（信息可能不完整）'

        # 生成报告按钮
        report_btn = ui.button(report_text, on_click=generate_report)\
            .props('color=amber-8').classes('w-full py-2 font-bold mt-2')
        if not report_enabled:
            report_btn.props('disable')

        # 报告预览区
        if state.analysis_result and state.report_generated:
            ui.separator()
            ui.label('📄 分析报告预览').style(f'font-size:13px; font-weight:bold; color:{COLOR_PRIMARY}')
            advice = state.analysis_result.get("final_review", state.analysis_result.get("content", "报告内容为空"))
            with ui.scroll_area().classes('max-h-80'):
                ui.label(advice[:5000] if advice else '报告内容为空').classes('text-xs whitespace-pre-wrap text-slate-700 dark:text-slate-300')

            with ui.row().classes('gap-2'):
                def save_txt():
                    ui.download(bytes(advice, 'utf-8'), '法律分析报告.txt')
                ui.button('💾 保存 TXT', on_click=save_txt).props('outline size=sm')


# ══════════════════════════════════════════
# 15. 知识库管理页面
# ══════════════════════════════════════════
def build_knowledge_page():
    with ui.element('div').classes('w-full shrink-0').style(f'background:{COLOR_PRIMARY}; height:40px; display:flex; align-items:center; padding:0 15px;'):
        ui.label('📊 RAG 知识库状态').classes('text-white text-sm font-bold')

    with ui.column().classes('w-full flex-1 min-h-0 p-4 overflow-y-auto bg-slate-50 dark:bg-zinc-950'):
        # 4列指标卡片
        with ui.row().classes('w-full gap-3'):
            vs_count = get_vector_count()
            law_files = get_law_file_count()
            cat_count = get_category_count()
            region_count = get_region_count()

            cards = [
                ("总切块数", vs_count, COLOR_PRIMARY),
                ("法律文件数", law_files, COLOR_INFO),
                ("分类数", cat_count, COLOR_SUCCESS),
                ("地域标签", region_count, COLOR_ACCENT),
            ]
            for title, value, color in cards:
                with ui.card().classes('flex-1 bg-white dark:bg-slate-800').style(f'border:1px solid {COLOR_BORDER};'):
                    ui.label(title).classes('text-xs text-slate-500 dark:text-slate-400')
                    ui.label(str(value)).style(f'font-size:24px; font-weight:bold; color:{color}')

        # 分类统计
        with ui.card().classes('w-full bg-white dark:bg-slate-800').style(f'border:1px solid {COLOR_BORDER};'):
            ui.label('📁 分类统计').style(f'font-size:13px; font-weight:bold; color:{COLOR_PRIMARY}')
            categories = get_categories()
            total = sum(categories.values()) or 1
            for cat, count in categories.items():
                pct = count / total
                with ui.row().classes('w-full items-center'):
                    ui.label(cat).classes('text-xs dark:text-slate-300').style('width:200px;')
                    ui.linear_progress(value=pct, color=COLOR_PRIMARY).classes('flex-1').props('instant-feedback')
                    ui.label(f'{count} 条').classes('text-xs text-slate-500 dark:text-slate-400')

        # 地域分布
        with ui.card().classes('w-full bg-white dark:bg-slate-800').style(f'border:1px solid {COLOR_BORDER};'):
            ui.label('🗺️ 地域分布').style(f'font-size:13px; font-weight:bold; color:{COLOR_PRIMARY}')
            regions = get_regions()
            if regions:
                sorted_regions = sorted(regions.items(), key=lambda x: x[1], reverse=True)
                mid = (len(sorted_regions) + 1) // 2
                with ui.row().classes('w-full gap-4'):
                    for col_idx in range(2):
                        with ui.column().classes('flex-1'):
                            items = sorted_regions[:mid] if col_idx == 0 else sorted_regions[mid:]
                            for region, count in items:
                                ui.label(f'• {region}: {count} 条').classes('text-xs text-slate-700 dark:text-slate-300')

        # 数据目录
        with ui.card().classes('w-full flex-1 bg-white dark:bg-slate-800').style(f'border:1px solid {COLOR_BORDER};'):
            ui.label('📂 数据目录结构').style(f'font-size:13px; font-weight:bold; color:{COLOR_PRIMARY}')
            data_dir = os.path.join(_BASE_DIR, "data")
            if os.path.exists(data_dir):
                tree = build_dir_tree(data_dir)
                ui.label(tree).classes('text-xs whitespace-pre').style('font-family: Consolas, monospace;')

        # 操作按钮
        with ui.row().classes('gap-2'):
            ui.button('🔍 扫描数据目录', on_click=lambda: ui.notify('请运行 python build_db.py 重建知识库', type='info'))\
                .props('color=primary')
            ui.label('💡 重建知识库请在终端运行: python build_db.py').classes('text-xs text-slate-500')


# ── 知识库辅助函数（单例缓存避免重复加载） ──
_vectorstore_cache = None
_vectorstore_cache_path = None


def _get_vectorstore():
    """获取向量库实例（带缓存，避免同一页面多次加载 pickle 文件）"""
    global _vectorstore_cache, _vectorstore_cache_path
    vs_path = os.path.join(_BASE_DIR, "vectorstore.pkl")
    if _vectorstore_cache is not None and _vectorstore_cache_path == vs_path:
        return _vectorstore_cache
    if not os.path.exists(vs_path):
        _vectorstore_cache = None
        _vectorstore_cache_path = None
        return None
    try:
        from simple_vectorstore import SimpleVectorStore
        vs = SimpleVectorStore(persist_path=vs_path)
        vs.load()
        _vectorstore_cache = vs
        _vectorstore_cache_path = vs_path
        return vs
    except Exception:
        _vectorstore_cache = None
        _vectorstore_cache_path = None
        return None


def get_vector_count():
    vs = _get_vectorstore()
    if vs is not None:
        try:
            return vs.count()
        except Exception:
            pass
    return "未建库"


def get_law_file_count():
    vs = _get_vectorstore()
    if vs is not None:
        try:
            data = vs.get()
            sources = set()
            for meta in data.get('metadatas', []):
                if meta:
                    sources.add(meta.get('law_name', '未知'))
            return len(sources)
        except Exception:
            pass
    return 0


def get_category_count():
    vs = _get_vectorstore()
    if vs is not None:
        try:
            data = vs.get()
            cats = set()
            for meta in data.get('metadatas', []):
                if meta:
                    cats.add(meta.get('category', '未分类'))
            return len(cats)
        except Exception:
            pass
    return 0


def get_region_count():
    vs = _get_vectorstore()
    if vs is not None:
        try:
            data = vs.get()
            regions = set()
            for meta in data.get('metadatas', []):
                if meta:
                    regions.add(meta.get('region', '未标记'))
            return len(regions)
        except Exception:
            pass
    return 0


def get_categories():
    vs = _get_vectorstore()
    cats = {}
    if vs is not None:
        try:
            data = vs.get()
            for meta in data.get('metadatas', []):
                if meta:
                    cat = meta.get('category', '未分类')
                    cats[cat] = cats.get(cat, 0) + 1
        except Exception:
            pass
    return cats


def get_regions():
    vs = _get_vectorstore()
    regions = {}
    if vs is not None:
        try:
            data = vs.get()
            for meta in data.get('metadatas', []):
                if meta:
                    r = meta.get('region', '未标记')
                    regions[r] = regions.get(r, 0) + 1
        except Exception:
            pass
    return regions

def build_dir_tree(path, indent=0):
    result = ""
    prefix = "  " * indent
    try:
        items = sorted(os.listdir(path))
        for item in items:
            full = os.path.join(path, item)
            if os.path.isdir(full):
                result += f"{prefix}📁 {item}/\n"
                result += build_dir_tree(full, indent + 1)
            else:
                size = os.path.getsize(full)
                size_str = f"{size/1024:.1f}KB" if size < 1024*1024 else f"{size/1024/1024:.1f}MB"
                result += f"{prefix}  📄 {item} ({size_str})\n"
    except PermissionError:
        result += f"{prefix}[权限不足]\n"
    return result


# ══════════════════════════════════════════
# 16. 启动入口
# ══════════════════════════════════════════
# ── 静态文件路径（UI 图片）──
# PyInstaller 打包后资源在 sys._MEIPASS 中
UI_IMAGES_DIR = os.path.join(_BASE_DIR, "UI 图片")
if os.path.isdir(UI_IMAGES_DIR):
    app.add_static_files('/ui_images', UI_IMAGES_DIR)
else:
    # 开发模式下回退到 SCRIPT_DIR
    UI_IMAGES_DIR = os.path.join(SCRIPT_DIR, "UI 图片")
    if os.path.isdir(UI_IMAGES_DIR):
        app.add_static_files('/ui_images', UI_IMAGES_DIR)

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        native=True,
        window_size=(1400, 850),
        title=f"{APP_TITLE} {read_version()}",
        reload=False,
    )
