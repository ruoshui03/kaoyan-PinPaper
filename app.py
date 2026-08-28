"""
考研数学《880》智能拼好卷 & 错题标练系统
核心逻辑：先标记错题 -> 默认以错题本题源组卷重练 (亦可随时切换全书模考)
"""
from __future__ import annotations

import base64
import binascii
import html
import io
import os
import random
import re
import uuid
from pathlib import Path

import streamlit as st

from core.bank_loader import BankLoader
from core.models import (
    ChapterCategory,
    DifficultyLevel,
    PaperBundle,
    PaperItem,
    PaperMode,
    QuestionItem,
    QuestionType,
    SubjectType,
    MATH_1_CHAPTERS,
    MATH_2_CHAPTERS,
    MATH_3_CHAPTERS,
)
from core.paper_engine import EngineRequest, PaperEngine
from core.pdf_service import PDFEdition, PDFService
from core.ai_tutor import AITutor
from core.state_manager import StateManager

# 题干里内联的 <img src="data:...base64,..."> 标签(loader 生成)
_INLINE_IMG_RE = re.compile(
    r'<img\s+src="data:(?P<mime>[^;]+);base64,(?P<data>[^"]+)"[^>]*>', re.S
)


def render_stem(text: str) -> None:
    """渲染题干:文字段走 st.markdown,内联 base64 图片走 st.image。

    Streamlit 的 markdown 消毒器会剥掉 <img src> 里的 data: URI(显示成裂图),
    故把题干按 <img> 切开,图片用原生 st.image 解码渲染,文字段仍走 markdown
    (unsafe_allow_html 供公式/管道表格)。PDF 路径不经过这里,仍用内联 HTML。
    """
    if not text:
        return
    pos = 0
    for m in _INLINE_IMG_RE.finditer(text):
        pre = text[pos:m.start()]
        if pre.strip():
            st.markdown(pre, unsafe_allow_html=True)
        try:
            st.image(base64.b64decode(m.group("data")))
        except (binascii.Error, ValueError):
            st.caption("（图片加载失败）")
        pos = m.end()
    rest = text[pos:]
    if rest.strip() or pos == 0:
        st.markdown(rest, unsafe_allow_html=True)


# =========================================================================
# 1. Page Configuration
# =========================================================================
st.set_page_config(
    page_title="考研拼好卷系统 · 智能组卷与错题攻坚平台",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. Global Singletons & Data Loader
# =========================================================================
@st.cache_resource(show_spinner="⚡ 正在初始化 880 题库与知识图谱引擎...")
def get_bank_loader(subject: SubjectType = SubjectType.MATH_1) -> BankLoader:
    loader = BankLoader(subject=subject)
    loader.load()
    return loader


# 运行环境判定：Streamlit Community Cloud 把应用挂载在 /mount/src/... 目录
IS_CLOUD = str(Path(__file__).resolve()).startswith("/mount")

# 身份与错题存储策略：
# - 链接带 ?u= → 一律沿用（支持"转发自己的完整链接"实现跨设备同步）
# - 云端无 ?u= → 每访客随机 u，各存各的；但云端硬盘会被清空，错题仅靠 URL 持久化，
#   故必须提示用户务必保存链接，否则记录丢失
# - 本地无 ?u= → 用固定档案名，错题长期落在本地文件，重开 localhost 即在，无需记链接
if "u" in st.query_params:
    current_user_param = st.query_params["u"]
elif "user" in st.query_params:
    current_user_param = st.query_params["user"]
elif IS_CLOUD:
    current_user_param = uuid.uuid4().hex[:8]
    st.query_params["u"] = current_user_param
else:
    current_user_param = "local"
    st.query_params["u"] = current_user_param

if "current_user_id" not in st.session_state or st.session_state.current_user_id != current_user_param:
    st.session_state.current_user_id = current_user_param
    st.session_state.state_mgr = StateManager(username=current_user_param)

state_mgr: StateManager = st.session_state.state_mgr
pdf_service = PDFService()


# Caching PDF generation so clicking buttons/checkboxes is instantaneous (0ms)
@st.cache_data(show_spinner="⚡ 正在后台生成高清矢量 PDF 导出流...")
def get_cached_pdf(paper_id: str, title: str, q_ids: tuple[str, ...], edition_str: str = "real_exam", subject_str: str = "数学一") -> bytes:
    sub = SubjectType(subject_str) if subject_str in [s.value for s in SubjectType] else SubjectType.MATH_1
    sub_loader = get_bank_loader(sub)
    q_items = [sub_loader.questions_by_id[qid] for qid in q_ids if qid in sub_loader.questions_by_id]
    paper_item = PaperItem(
        title=title,
        paper_id=paper_id,
        subject=sub,
        mode=PaperMode.FULL_10_6_6,
        questions=q_items,
    )
    edition = PDFEdition(edition_str) if edition_str in [e.value for e in PDFEdition] else PDFEdition.REAL_EXAM
    return pdf_service.render_pdf_bytes(paper_item, edition=edition)


@st.cache_data(show_spinner="⚡ 正在生成纯净 HTML 试卷流...")
def get_cached_html(paper_id: str, title: str, q_ids: tuple[str, ...], edition_str: str = "real_exam", subject_str: str = "数学一") -> str:
    sub = SubjectType(subject_str) if subject_str in [s.value for s in SubjectType] else SubjectType.MATH_1
    sub_loader = get_bank_loader(sub)
    q_items = [sub_loader.questions_by_id[qid] for qid in q_ids if qid in sub_loader.questions_by_id]
    paper_item = PaperItem(
        title=title,
        paper_id=paper_id,
        subject=sub,
        mode=PaperMode.FULL_10_6_6,
        questions=q_items,
    )
    edition = PDFEdition(edition_str) if edition_str in [e.value for e in PDFEdition] else PDFEdition.REAL_EXAM
    return pdf_service.generate_html(paper_item, edition=edition)


# =========================================================================
# 3. Modern Clean Academic CSS Design System
# =========================================================================
def inject_modern_theme():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap');

        /* Global Font and Base Styling */
        html, body, [class*="css"] {
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif !important;
            color: #1e293b;
        }

        /* Top Modern Hero Card */
        .app-hero {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 20px 28px;
            margin-bottom: 24px;
            box-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.05);
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 20px;
        }
        .app-hero-main {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .app-hero-icon {
            width: 48px;
            height: 48px;
            background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
            border: 1px solid #bfdbfe;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            flex-shrink: 0;
        }
        .app-hero-title {
            font-size: 21px !important;   /* !important 压过 Streamlit 默认 h1 的 44px */
            font-weight: 800;
            color: #0f172a;
            letter-spacing: -0.02em;
            margin: 0;
            padding: 0;
            line-height: 1.3;
        }
        .app-hero-desc {
            font-size: 13px;
            color: #64748b;
            margin-top: 4px;
            font-weight: 500;
        }
        .app-hero-badge {
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            color: #2563eb;
            padding: 8px 18px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 700;
            white-space: nowrap;
            flex-shrink: 0;
            box-shadow: 0 2px 4px rgba(37, 99, 235, 0.06);
        }
        /* 手机窄屏:hero 竖向堆叠，标题独占整行不被挤成竖排 */
        @media (max-width: 640px) {
            .app-hero {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
                padding: 16px 18px;
            }
            .app-hero-main {
                gap: 12px;
                width: 100%;
            }
            .app-hero-title {
                font-size: 18px !important;   /* 手机再收一号，确保七字一行 */
                white-space: nowrap;
            }
            .app-hero-desc {
                font-size: 12px;
            }
            .app-hero-badge {
                white-space: normal;   /* 徽章移到下方，允许自然换行 */
                align-self: flex-start;
            }
        }

        /* Modern Card Styling */
        .glass-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 14px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px -2px rgba(15, 23, 42, 0.04);
            transition: all 0.2s ease;
        }

        /* Question Badges */
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 3px 9px;
            border-radius: 6px;
            font-size: 11.5px;
            font-weight: 700;
            margin-right: 6px;
        }
        .badge-basic { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
        .badge-comp { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
        .badge-adv { background: #faf5ff; color: #7e22ce; border: 1px solid #e9d5ff; }
        .badge-ch { background: #f8fafc; color: #475569; border: 1px solid #e2e8f0; }
        .badge-tag { background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }
        .badge-wrong { background: #fff1f2; color: #be123c; border: 1px solid #fecdd3; }

        /* Formula & Math Typography */
        .katex, .katex-display {
            font-size: 1.06em !important;
            color: #0f172a !important;
        }

        /* Pitfall & Solution Callout */
        .pitfall-callout {
            background: #fffbeb;
            border-left: 4px solid #f59e0b;
            padding: 14px 18px;
            border-radius: 0 10px 10px 0;
            margin: 12px 0;
            font-size: 13.5px;
            color: #92400e;
            border-top: 1px solid #fef3c7;
            border-right: 1px solid #fef3c7;
            border-bottom: 1px solid #fef3c7;
        }

        /* Radar Matrix Badges */
        .radar-pill {
            display: inline-block;
            padding: 5px 12px;
            border-radius: 8px;
            font-size: 12px;
            margin: 4px;
            font-weight: 600;
        }
        .radar-pill-done {
            background: #ecfdf5;
            color: #047857;
            border: 1px solid #a7f3d0;
        }
        .radar-pill-todo {
            background: #f8fafc;
            color: #64748b;
            border: 1px dashed #cbd5e1;
        }

        /* Streamlit Tab Styles */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            border-bottom: 2px solid #e2e8f0;
            margin-bottom: 24px;
        }
        .stTabs [data-baseweb="tab"] {
            height: 46px;
            font-weight: 700;
            font-size: 14.5px;
            border-radius: 8px 8px 0 0;
            padding: 0 20px;
            color: #64748b;
        }
        .stTabs [aria-selected="true"] {
            color: #2563eb !important;
        }

        /* Metric Enhancement */
        [data-testid="stMetricValue"] {
            font-family: 'Plus Jakarta Sans', sans-serif !important;
            font-weight: 800 !important;
            color: #0f172a !important;
        }

        /* Question Card Container */
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px !important;
            border-color: #e2e8f0 !important;
            background: #ffffff !important;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.03) !important;
            transition: all 0.2s ease !important;
            margin-bottom: 14px !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:hover {
            border-color: #cbd5e1 !important;
            box-shadow: 0 4px 14px -2px rgba(15, 23, 42, 0.05) !important;
        }

        /* BaseWeb Select & Multiselect "No results" / "No options" localization */
        div[data-baseweb="menu"] li[aria-disabled="true"],
        div[data-baseweb="popover"] li[aria-disabled="true"],
        div[data-baseweb="menu"] div[aria-disabled="true"],
        div[data-baseweb="popover"] div[aria-disabled="true"] {
            font-size: 0 !important;
            min-height: 36px !important;
            display: flex !important;
            align-items: center !important;
        }
        div[data-baseweb="menu"] li[aria-disabled="true"]::after,
        div[data-baseweb="popover"] li[aria-disabled="true"]::after,
        div[data-baseweb="menu"] div[aria-disabled="true"]::after,
        div[data-baseweb="popover"] div[aria-disabled="true"]::after {
            content: "暂无匹配结果" !important;
            font-size: 13.5px !important;
            color: #94a3b8 !important;
            font-weight: 500 !important;
            padding: 6px 12px !important;
            display: block !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_modern_theme()


# =========================================================================
# 4. Global Sidebar Controls (Book & Subject & Wrong Book & AI)
# =========================================================================
with st.sidebar:
    st.markdown("### 📚 考研拼好卷系统")

    # 1. 优先选择科目
    selected_subject_str = st.selectbox(
        "🎯 考研数学科目",
        options=["数学一", "数学二", "数学三", "自定义"],
        index=0,
    )
    if selected_subject_str == "数学一":
        current_subject = SubjectType.MATH_1
    elif selected_subject_str == "数学二":
        current_subject = SubjectType.MATH_2
    elif selected_subject_str == "数学三":
        current_subject = SubjectType.MATH_3
    else:
        current_subject = SubjectType.CUSTOM

    # 2. 再选择参考书籍 (支持多选汇聚题库池)
    available_books = ["880"]
    selected_books = st.multiselect(
        "📚 选择参考书籍",
        options=available_books,
        default=available_books,
        placeholder="请选择参考书籍...",
        help="勾选需要纳入组卷题库池的书籍，支持多选",
    )
    current_books_str = "、".join(selected_books) if selected_books else "未选择书籍"

    # 动态加载对应科目题库并根据多选书籍进行汇聚
    loader = get_bank_loader(current_subject if current_subject != SubjectType.CUSTOM else SubjectType.MATH_1)
    raw_questions = loader.load()
    all_questions = [q for q in raw_questions if getattr(q, "book", "880") in selected_books]

    # 动态提炼章节结构，彻底避免写死任何固定参考书的章节划分与数量
    loaded_chapters = []
    seen_ch = set()
    for q in all_questions:
        if q.chapter and q.chapter not in seen_ch:
            seen_ch.add(q.chapter)
            loaded_chapters.append(q.chapter)
    default_target_chapters = set(loaded_chapters)

    # 科目变更监听与右侧试卷状态自动重置
    if "last_selected_subject" not in st.session_state:
        st.session_state.last_selected_subject = selected_subject_str
    elif st.session_state.last_selected_subject != selected_subject_str:
        st.session_state.last_selected_subject = selected_subject_str
        st.session_state.current_paper_p1 = None
        st.session_state.current_bundle_p1 = None

    # 根据当前科目自动挂载专属错题本（数一/数二/数三相互独立隔离）
    active_sub = current_subject if current_subject != SubjectType.CUSTOM else SubjectType.MATH_1
    state_mgr = StateManager(username=current_user_param, subject=active_sub)

    # URL 位图：每科目一个查询参数键，可在同一网址里并存三科错题状态
    URL_SUBJECT_KEY = {
        SubjectType.MATH_1: "d1",
        SubjectType.MATH_2: "d2",
        SubjectType.MATH_3: "d3",
    }
    url_data_key = URL_SUBJECT_KEY.get(active_sub)
    # seen 位图参数键(已抽过的题),与错题位图 d1/d2/d3 独立并存
    URL_SEEN_KEY = {SubjectType.MATH_1: "n1", SubjectType.MATH_2: "n2", SubjectType.MATH_3: "n3"}
    url_seen_key = URL_SEEN_KEY.get(active_sub)
    # 位图 canonical 列表锁定到具体书籍，独立于科目里是否还有别的书。
    # 今天整科==880，故此列表与全量一致、签名不变、现有 URL 不失效；
    # 将来加第二本书时，880 的题号列表/顺序/签名保持稳定 → 880 旧 URL 依然有效。
    # 【待办·第二本书】该书需自己的 canonical 列表 + 独立参数(如 d1b)，
    #   并配合错题本 book::id 复合键防撞号；届时按其真实题号规则一次设计。
    URL_BITMAP_BOOK = "880"
    canonical_ids = loader.canonical_ids(book=URL_BITMAP_BOOK)

    # 首次进入本科目且网址带错题码时，从 URL 恢复（无后端跨设备恢复）
    if url_data_key and current_subject != SubjectType.CUSTOM:
        restore_flag = f"_url_restored_{active_sub.value}"
        if restore_flag not in st.session_state:
            st.session_state[restore_flag] = True
            incoming_code = st.query_params.get(url_data_key)
            if incoming_code:
                n_restored, restore_status = state_mgr.apply_url_code(incoming_code, canonical_ids)
                if restore_status == "stale":
                    st.session_state["_url_restore_stale"] = active_sub.value
            # 恢复"已抽过题"(seen)——与错题码独立,合并进本地累积集合
            incoming_seen = st.query_params.get(url_seen_key) if url_seen_key else None
            if incoming_seen:
                state_mgr.apply_seen_url_code(incoming_seen, canonical_ids)

    # URL 试卷码：记住上次生成的是哪几道题（不含组卷配置），做完后跨设备查阅答案。
    # 每科目一个参数键 q1/q2/q3。当右侧无当前试卷时（首次进入 / 切科目回来）从 URL 恢复。
    PAPER_URL_KEY = {SubjectType.MATH_1: "q1", SubjectType.MATH_2: "q2", SubjectType.MATH_3: "q3"}
    paper_url_key = PAPER_URL_KEY.get(active_sub)
    if paper_url_key and current_subject != SubjectType.CUSTOM and not st.session_state.get("current_paper_p1"):
        # 优先从 URL 的 q 码恢复（跨设备）；无 q 码时回退到本地文件里"上次生成的卷"（本地重开）
        papers_qids: list[list[str]] = []
        pcode = st.query_params.get(paper_url_key)
        if pcode:
            decoded, pstatus = StateManager.decode_papers_code(pcode, canonical_ids)
            if pstatus == "ok" and decoded:
                papers_qids = decoded
        if not papers_qids and state_mgr.last_papers_qids:
            # 本地存档；过滤当前题库仍存在的题号，避免题库变动后错位
            valid = set(canonical_ids)
            papers_qids = [[q for q in p if q in valid] for p in state_mgr.last_papers_qids]
            papers_qids = [p for p in papers_qids if p]
        if papers_qids:
            def _rebuild_paper(qids: list[str], idx: int, total: int) -> PaperItem:
                qs = [loader.questions_by_id[q] for q in qids if q in loader.questions_by_id]
                label = f"（{chr(65 + idx)}卷）" if total > 1 else ""
                return PaperItem(
                    title=f"上次生成的{active_sub.value}试卷{label}",
                    paper_id=f"RESTORED-{active_sub.value}-{idx}",
                    subject=active_sub,
                    mode=PaperMode.CUSTOM,
                    questions=qs,
                )
            built = [_rebuild_paper(q, i, len(papers_qids)) for i, q in enumerate(papers_qids) if q]
            if len(built) == 1:
                st.session_state.current_paper_p1 = built[0]
                st.session_state.current_bundle_p1 = None
            elif len(built) > 1:
                st.session_state.current_bundle_p1 = PaperBundle(
                    bundle_id=f"RESTORED-{active_sub.value}",
                    title=f"上次生成的{active_sub.value}联考套卷",
                    subject=active_sub,
                    papers=built,
                )
                st.session_state.current_paper_p1 = built[0]

    # 当前科目的活跃错题池与历史错题池计算
    active_wrong_ids = state_mgr.get_active_wrong_question_ids()
    all_wrong_ids = state_mgr.get_all_wrong_question_ids()
    subject_active_wrong_pool = [q for q in all_questions if q.id in active_wrong_ids]
    subject_wrong_pool = subject_active_wrong_pool
    subject_wrong_count = len(subject_active_wrong_pool)
    past_wrong_count = len([q for q in all_questions if q.id in all_wrong_ids and not state_mgr.is_in_active_pool(q.id)])
    repeated_wrong_count = sum(1 for q in subject_active_wrong_pool if state_mgr.get_wrong_count(q.id) >= 2)

    # 极速响应回调函数 (基于 on_click 单程更新，彻底消除双重刷新卡顿)
    def cb_toggle_wrong(qid: str):
        state_mgr.toggle_wrong_question(qid)

    def cb_remove_wrong(qid: str):
        state_mgr.remove_wrong_question(qid)

    def cb_archive_to_history(qid: str):
        state_mgr.mark_solved_correctly(qid)

    def cb_reactivate_wrong(qid: str):
        state_mgr.reactivate_to_pool(qid)

    def cb_inc_wrong(qid: str, delta: int = 1):
        state_mgr.increment_wrong_count(qid, delta=delta)

    st.markdown("---")
    st.markdown("### 📕 错题本画像")
    sb_c1, sb_c2 = st.columns(2)
    with sb_c1:
        st.metric(
            label="🎯 待练错题",
            value=f"{subject_wrong_count} 题",
        )
    with sb_c2:
        st.metric(
            label="🏆 历史错题",
            value=f"{past_wrong_count} 题",
        )

    st.metric(
        label="🔥 顽固错题",
        value=f"{repeated_wrong_count} 题",
    )

    if subject_wrong_count > 0 or past_wrong_count > 0:
        if st.button("🗑️ 清空所有错题记录", use_container_width=True):
            state_mgr.clear_all_wrong()
            st.success("已清空错题记录！")
            st.rerun()

    if st.session_state.get("_url_restore_stale") == active_sub.value:
        st.warning("⚠️ 网址中的错题码与当前题库版本不匹配（题库已更新），未自动恢复，以本地记录为准。")

    if IS_CLOUD:
        st.markdown(
            "⚠️ **必须保存本页链接！** 你的错题记录**与上次生成的试卷**都已编码进当前网址（连同 AI 服务商 / 模型）。"
            "本服务运行在云端，**不保存你的数据**——一旦关闭页面又没存下这条链接，"
            "**错题记录和试卷将永久丢失且无法找回**。请立刻【收藏本页】或复制网址存好，换设备时打开它即可恢复。"
            "（API Key 出于安全不写入网址。）另建议定期用下方【导出错题本备份】再存一份 JSON。"
        )
    else:
        st.caption(
            "🔗 错题记录**与上次生成的试卷**已自动保存在本机文件，重开本页即在，无需记链接。"
            "该网址也编码了你的错题、试卷与 AI 配置，复制它可在其他设备恢复（API Key 不写入网址）。"
        )

    st.markdown("---")
    st.markdown("### 🤖 AI 名师答疑")

    preset_providers = {
        "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
        "DeepSeek-R1": ("https://api.deepseek.com", "deepseek-reasoner"),
        "SiliconFlow": ("https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V3"),
        "OpenAI": ("https://api.openai.com/v1", "gpt-4o"),
        "通义千问": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        "智谱清言": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
        "Ollama 本地": ("http://localhost:11434/v1", "llama3"),
        "自定义": ("", ""),
    }

    # 首次进入时用网址里保存的 Base URL / Model 作为初值（Key 永不进 URL）
    if "_ai_cfg_seeded" not in st.session_state:
        st.session_state["_ai_cfg_seeded"] = True
        st.session_state.setdefault("ai_base_url", st.query_params.get("au") or os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"))
        st.session_state.setdefault("ai_model", st.query_params.get("am") or "deepseek-chat")

    # 切换预设服务商时，自动带出其 Base URL 与 Model（自定义不覆盖已填内容）
    def _apply_provider_preset():
        url, model = preset_providers.get(st.session_state.get("ai_provider"), ("", ""))
        if url:
            st.session_state["ai_base_url"] = url
        if model:
            st.session_state["ai_model"] = model

    selected_provider = st.selectbox(
        "服务提供商",
        options=list(preset_providers.keys()),
        index=0,
        key="ai_provider",
        on_change=_apply_provider_preset,
        help="选择预设提供商或选择自定义以连接任意兼容 OpenAI 规范的大模型 API。",
    )

    user_api_url = st.text_input(
        "API Base URL",
        key="ai_base_url",
        help="大模型 API Base URL（例如 https://api.deepseek.com 或 https://api.openai.com/v1）。",
    )
    user_api_key = st.text_input(
        "API Key",
        value=os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
        type="password",
        help="出于安全，API Key 不会写入网址，仅本会话使用；也可用环境变量预置。",
    )
    user_model_name = st.text_input(
        "Model 模型名称",
        key="ai_model",
        help="调用的模型名称（例如 deepseek-chat, gpt-4o, qwen-plus 等）。",
    )


# =========================================================================
# 5. Top Modern Hero Header
# =========================================================================
st.markdown(
    f"""
    <div class="app-hero">
        <div class="app-hero-main">
            <div class="app-hero-icon">📚</div>
            <div>
                <h1 class="app-hero-title">考研拼好卷系统</h1>
                <div class="app-hero-desc">跨题库精准拼卷 · 经典书目穿透 · 错题靶向攻坚 · 智能自适应组卷</div>
            </div>
        </div>
        <div class="app-hero-badge">
            📚 {current_books_str} · 🔥 {current_subject.value} · {len(loaded_chapters)} 章 · {len(all_questions)} 题
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================================================================
# 6. Three Core Workspaces (Tabs)
# =========================================================================
tab_paper_hub, tab_marker_hub, tab_coverage_hub = st.tabs([
    "🎯 智能拼好卷",
    "🏷️ 题库逐题标错",
    "📈 全科考点雷达",
])


# -------------------------------------------------------------------------
# WORKSPACE 1: 智能拼好卷大厅 (核心组卷与刷题，默认以错题组卷)
# -------------------------------------------------------------------------
with tab_paper_hub:
    st.markdown("#### 🎯 智能拼卷配置")

    # 1. 核心题源配置：错题占比滑块（错题 : 新题 混合，错题不足自动用新题补齐）
    src_col1, src_col2 = st.columns([2, 1])
    with src_col1:
        default_ratio = 70 if subject_wrong_count > 0 else 0
        wrong_ratio_pct = st.slider(
            "🎯 错题占比（其余用新题补足；错题不够时自动用新题补齐）",
            min_value=0, max_value=100, value=default_ratio, step=10,
            key=f"p1_wrong_ratio_{current_subject.value}",
            help="0% = 全书模考（全新题）；100% = 尽量全用错题，不足部分用新题补齐；中间值按比例混合。",
        )
        wrong_ratio = wrong_ratio_pct / 100.0
    with src_col2:
        if wrong_ratio_pct > 0 and subject_wrong_count == 0:
            st.warning("⚠️ 当前错题池暂无题目，将全部用新题组卷。请前往【逐题标错】录入错题。")
        else:
            st.caption(f"当前已标错题 {subject_wrong_count} 题 · 全书 {len(all_questions)} 题")
        exclude_seen = st.checkbox(
            "🚫 避免重复抽题（抽过的新题不再抽）",
            value=True,
            key=f"p1_exclude_seen_{current_subject.value}",
            help="开启后组卷会跳过你之前抽到过的新题；抽完全书后自动重新允许。错题重练不受影响。",
        )

    # 2. 规格与难度配置
    cfg_col1, cfg_col2, cfg_col3 = st.columns([1.5, 1.5, 1.5])
    with cfg_col1:
        mode_choice = st.radio(
            "拼卷规格",
            options=[
                PaperMode.FULL_10_6_6.value,
                PaperMode.SPRINT_5_3_3.value,
                PaperMode.BUNDLE_3_PAPERS.value,
                PaperMode.CUSTOM.value,
            ],
            index=0,
            key=f"p1_mode_{current_subject.value}",
        )
        current_mode = PaperMode(mode_choice)

        st.markdown("##### 按照真题大纲")
        if current_subject == SubjectType.MATH_2:
            cat_c1, cat_c2 = st.columns(2)
            with cat_c1:
                chk_math = st.checkbox("高等数学", value=True, key=f"p1_chk_math_{current_subject.value}")
            with cat_c2:
                chk_linalg = st.checkbox("线性代数", value=True, key=f"p1_chk_linalg_{current_subject.value}")
            chk_prob = False
        else:
            cat_c1, cat_c2, cat_c3 = st.columns(3)
            with cat_c1:
                chk_math = st.checkbox("高等数学", value=True, key=f"p1_chk_math_{current_subject.value}")
            with cat_c2:
                chk_linalg = st.checkbox("线性代数", value=True, key=f"p1_chk_linalg_{current_subject.value}")
            with cat_c3:
                chk_prob = st.checkbox("概率论", value=True, key=f"p1_chk_prob_{current_subject.value}")

        enabled_categories = set()
        if chk_math: enabled_categories.add(ChapterCategory.ADVANCED_MATH)
        if chk_linalg: enabled_categories.add(ChapterCategory.LINEAR_ALGEBRA)
        if chk_prob: enabled_categories.add(ChapterCategory.PROBABILITY)
        if not enabled_categories:
            enabled_categories = {ChapterCategory.ADVANCED_MATH, ChapterCategory.LINEAR_ALGEBRA} if current_subject == SubjectType.MATH_2 else {ChapterCategory.ADVANCED_MATH, ChapterCategory.LINEAR_ALGEBRA, ChapterCategory.PROBABILITY}

    with cfg_col2:
        st.markdown("##### ⚖️ 难度梯度倾向")
        w_basic = st.slider("基础题倾向", 0.0, 2.0, 1.0, 0.1, key="p1_basic")
        w_comp = st.slider("综合题倾向", 0.0, 2.0, 1.2, 0.1, key="p1_comp")
        w_adv = st.slider("拓展题倾向", 0.0, 2.0, 0.8, 0.1, key="p1_adv")
        diff_weights = {
            DifficultyLevel.BASIC: w_basic,
            DifficultyLevel.COMPREHENSIVE: w_comp,
            DifficultyLevel.ADVANCED: w_adv,
        }

    with cfg_col3:
        st.markdown("##### 🎯 专项考点标签")
        selected_tag = st.selectbox(
            "考点标签",
            options=["全部", "高频经典", "易错点", "计算量大", "综合压轴"],
            index=0,
            key="p1_tag",
        )
        custom_counts = {}
        custom_category_weights = {}
        if current_mode == PaperMode.CUSTOM:
            st.markdown("##### 自由题量配置")
            cc1, cc2, cc3 = st.columns(3)
            with cc1: custom_counts[QuestionType.CHOICE] = st.number_input("选择题数量", 0, 30, 10, key="custom_qc")
            with cc2: custom_counts[QuestionType.FILL_BLANK] = st.number_input("填空题数量", 0, 20, 6, key="custom_qf")
            with cc3: custom_counts[QuestionType.SOLUTION] = st.number_input("解答题数量", 0, 15, 6, key="custom_qs")

            st.markdown("##### 学科比例配置")
            if current_subject == SubjectType.MATH_2:
                rc1, rc2 = st.columns(2)
                with rc1: w_math = st.number_input("高等数学比例", min_value=0, max_value=100, value=78, step=1, key="c_w_math")
                with rc2: w_linalg = st.number_input("线性代数比例", min_value=0, max_value=100, value=22, step=1, key="c_w_linalg")
                custom_category_weights = {
                    ChapterCategory.ADVANCED_MATH: float(w_math),
                    ChapterCategory.LINEAR_ALGEBRA: float(w_linalg),
                }
            else:
                rc1, rc2, rc3 = st.columns(3)
                with rc1: w_math = st.number_input("高等数学比例", min_value=0, max_value=100, value=56, step=1, key="c_w_math")
                with rc2: w_linalg = st.number_input("线性代数比例", min_value=0, max_value=100, value=22, step=1, key="c_w_linalg")
                with rc3: w_prob = st.number_input("概率论比例", min_value=0, max_value=100, value=22, step=1, key="c_w_prob")
                custom_category_weights = {
                    ChapterCategory.ADVANCED_MATH: float(w_math),
                    ChapterCategory.LINEAR_ALGEBRA: float(w_linalg),
                    ChapterCategory.PROBABILITY: float(w_prob),
                }

    # 3. 组卷触发按钮
    st.markdown("---")
    act_col1, act_col2 = st.columns([3, 1])
    with act_col1:
        button_title = f"🚀 立即生成 {current_subject.value} 试卷"
        start_assemble = st.button(button_title, type="primary", use_container_width=True, key=f"p1_gen_btn_{current_subject.value}")
    with act_col2:
        if st.button("🔄 重置覆盖轮次", use_container_width=True, key="p1_reset_cycle"):
            state_mgr.reset_coverage_cycle()
            st.success("已重置覆盖轮次！")
            st.rerun()

    # 仅在点击生成按钮时触发组卷
    if start_assemble:
        with st.spinner(f"⚡ 正在为您智能组装试卷..."):
            # 候选池始终是全书；错题以"优先池 + 占比"注入，错题不足时自动用新题补齐
            candidate_pool = all_questions
            effective_ratio = wrong_ratio if subject_wrong_count > 0 else 0.0
            wrong_id_set = {q.id for q in subject_wrong_pool}
            if effective_ratio >= 0.99:
                target_title = f"考研数学《880》{current_subject.value} 错题专项重练卷"
            elif effective_ratio > 0:
                target_title = f"考研数学《880》{current_subject.value} 错题强化卷（错题{wrong_ratio_pct}%）"
            else:
                target_title = f"考研数学《880》{current_subject.value} 智能拼好卷"

            engine = PaperEngine(candidate_pool)
            req = EngineRequest(
                title=target_title,
                subject=current_subject,
                mode=current_mode,
                target_chapters=default_target_chapters,
                enabled_categories=enabled_categories,
                category_weights=custom_category_weights,
                type_counts=custom_counts,
                difficulty_weights=diff_weights,
                tag_filter=selected_tag,
                seed=random.randint(1000, 99999),
                historical_covered_chapters=state_mgr.historical_covered_chapters,
                historical_seen_question_ids=state_mgr.historical_seen_ids,
                candidate_question_pool=candidate_pool,
                priority_pool_ids=wrong_id_set,
                priority_ratio=effective_ratio,
                exclude_seen=exclude_seen,
            )
            if current_mode == PaperMode.BUNDLE_3_PAPERS:
                bundle = engine.generate_bundle(req, bundle_size=3)
                st.session_state.current_bundle_p1 = bundle
                st.session_state.current_paper_p1 = bundle.papers[0]
                for p in bundle.papers:
                    state_mgr.record_paper_generation(p.questions)
                state_mgr.set_last_papers([[q.id for q in p.questions] for p in bundle.papers])
            else:
                paper = engine.generate_single_paper(req)
                st.session_state.current_paper_p1 = paper
                st.session_state.current_bundle_p1 = None
                state_mgr.record_paper_generation(paper.questions)
                state_mgr.set_last_papers([[q.id for q in paper.questions]])

    # 渲染当前生成的试卷
    active_paper: PaperItem | None = st.session_state.get("current_paper_p1")
    active_bundle: PaperBundle | None = st.session_state.get("current_bundle_p1")

    if not active_paper:
        st.markdown(
            f"""
            <div class="glass-card" style="text-align:center; padding: 48px 24px; margin-top:20px; background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);">
                <div style="font-size: 36px; margin-bottom: 12px;">🎯</div>
                <h3 style="color:#0f172a; font-size:18px; font-weight:800; margin-bottom:8px;">880 {current_subject.value} 拼卷大厅就绪</h3>
                <p style="color:#64748b; font-size:14px; max-width:640px; margin:0 auto 20px auto; line-height:1.6;">
                    系统默认从您标记的错题池中精准抽题重练。您也可以随时切换为全书模考。请调整上方规格后点击立即生成试卷。
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        if active_bundle:
            st.markdown(f"##### 📦 {active_bundle.title}")
            bundle_labels = [f"📄 {p.title}" for p in active_bundle.papers]
            selected_b_idx = st.radio(
                "分卷切换：",
                options=list(range(len(bundle_labels))),
                format_func=lambda i: bundle_labels[i],
                horizontal=True,
                key=f"p1_bundle_tabs_{current_subject.value}",
            )
            active_paper = active_bundle.papers[selected_b_idx]

        ai_t = AITutor(api_key=user_api_key, base_url=user_api_url, model=user_model_name)

        st.markdown("---")
        top_bar_c1, top_bar_c2 = st.columns([3.5, 1.2])
        with top_bar_c1:
            st.markdown(f"### 📝 {active_paper.title}")
            st.caption(f"卷号: {active_paper.paper_id} · 共 {active_paper.total_count} 题 · 选择 {len(active_paper.choice_questions)} 空 {len(active_paper.fill_questions)} 答 {len(active_paper.solution_questions)}")
        with top_bar_c2:
            show_all_ans = st.checkbox("📖 展开全部解析", value=False, key="p1_show_ans_cb")

        # 立即展示完整题目列表（0 毫秒即时呈现，不阻塞等待后台 PDF 编译）
        sections = [
            ("一、选择题", active_paper.choice_questions),
            ("二、填空题", active_paper.fill_questions),
            ("三、解答题", active_paper.solution_questions),
        ]

        q_idx = 1
        for title, q_list in sections:
            if not q_list:
                continue
            st.markdown(f"#### {title}")
            for q in q_list:
                is_active = state_mgr.is_in_active_pool(q.id)
                is_temp_mastered = state_mgr.is_temporarily_mastered(q.id)
                w_cnt = state_mgr.get_wrong_count(q.id)
                diff_b = "badge-basic" if q.difficulty == DifficultyLevel.BASIC else ("badge-adv" if q.difficulty == DifficultyLevel.ADVANCED else "badge-comp")

                with st.container(border=True):
                    # Header row with integrated top-right toggle & count buttons
                    if is_active:
                        c_h1, c_h2, c_h3 = st.columns([3.8, 1.4, 0.6])
                        with c_h1:
                            card_header_html = (
                                f'<div style="display:flex; align-items:center; margin-top:2px;">'
                                f'<span style="font-weight:800; font-size:16px; color:#000000; margin-right:4px;">{q_idx}.</span>'
                                f'</div>'
                            )
                            st.markdown(card_header_html, unsafe_allow_html=True)
                        with c_h2:
                            st.button(f"❌ 移入历史错题", key=f"p1_arch_{q.id}_{q_idx}_{current_subject.value}", type="primary", use_container_width=True, help="做题已掌握？点击移入历史错题档案（保留做错次数，不再强制抽取）", on_click=cb_archive_to_history, args=(q.id,))
                        with c_h3:
                            st.button("➕1", key=f"p1_inc_{q.id}_{q_idx}_{current_subject.value}", use_container_width=True, help="又做错了？点击做错次数+1", on_click=cb_inc_wrong, args=(q.id, 1))

                    elif is_temp_mastered:
                        c_h1, c_h2, c_h3 = st.columns([3.8, 1.4, 0.9])
                        with c_h1:
                            card_header_html = (
                                f'<div style="display:flex; align-items:center; margin-top:2px;">'
                                f'<span style="font-weight:800; font-size:16px; color:#000000; margin-right:4px;">{q_idx}.</span>'
                                f'</div>'
                            )
                            st.markdown(card_header_html, unsafe_allow_html=True)
                        with c_h2:
                            st.button("🎯 放回待练池", key=f"p1_react_{q.id}_{q_idx}_{current_subject.value}", type="primary", use_container_width=True, help="点击重新放回活跃错题池参与组卷抽题", on_click=cb_reactivate_wrong, args=(q.id,))
                        with c_h3:
                            st.button("🗑️ 彻底删除", key=f"p1_del_{q.id}_{q_idx}_{current_subject.value}", use_container_width=True, help="彻底从错题记录中移除", on_click=cb_remove_wrong, args=(q.id,))

                    else:
                        c_h1, c_h2 = st.columns([4.4, 1.2])
                        with c_h1:
                            card_header_html = (
                                f'<div style="display:flex; align-items:center; margin-top:2px;">'
                                f'<span style="font-weight:800; font-size:16px; color:#000000; margin-right:4px;">{q_idx}.</span>'
                                f'</div>'
                            )
                            st.markdown(card_header_html, unsafe_allow_html=True)
                        with c_h2:
                            st.button("○ 标为错题", key=f"p1_mark_{q.id}_{q_idx}_{current_subject.value}", use_container_width=True, help="做错了？点击放入待练错题池", on_click=cb_toggle_wrong, args=(q.id,))

                    # Question Stem（内联图片走 st.image,文字/公式/表格走 markdown)
                    render_stem(q.stem)

                    # Options
                    if q.options:
                        oc1, oc2 = st.columns(2)
                        for oi, opt in enumerate(q.options):
                            if oi % 2 == 0:
                                with oc1: st.markdown(opt)
                            else:
                                with oc2: st.markdown(opt)

                    # Solutions Callout (含书籍、难度、章节、ID、题目标签与做错统计)
                    if show_all_ans or st.checkbox(f"查看答案与解析", key=f"p1_ans_cb_{q.id}_{q_idx}_{current_subject.value}"):
                        tags_html = "".join(f'<span class="badge badge-tag">#{t}</span>' for t in q.tags) if q.tags else ""
                        if is_active:
                            if w_cnt >= 2:
                                status_badge = f'<span class="badge" style="background:#fff1f2; color:#be123c; border:1px solid #fda4af; font-weight:700;">🔥 顽固错题 · 累计做错 {w_cnt} 次</span>'
                            else:
                                status_badge = f'<span class="badge badge-adv" style="font-weight:700;">🎯 待练错题 · 累计做错 {w_cnt} 次</span>'
                        elif is_temp_mastered:
                            status_badge = f'<span class="badge" style="background:#fef3c7; color:#92400e; border:1px solid #fcd34d; font-weight:700;">🏆 历史错题 · 历史做错 {w_cnt} 次</span>'
                        else:
                            status_badge = ''

                        meta_row = (
                            f'<div style="display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:8px;">'
                            f'<span class="badge badge-ch">《{getattr(q, "book", "880")}》</span>'
                            f'<span class="badge {diff_b}">[{q.difficulty.value}]</span>'
                            f'<span class="badge badge-ch">{q.chapter}</span>'
                            f'<span style="font-size:11.5px; color:#64748b; font-family:monospace; margin-right:4px;">ID: {q.id}</span>'
                            f'{tags_html} {status_badge}'
                            f'</div>'
                        )

                        st.markdown(meta_row, unsafe_allow_html=True)
                        if q.answer: st.markdown(f"**【参考答案】**：`{q.answer}`")
                        if q.solution: st.markdown(f"**【详细解析】**：\n{q.solution}")

                    with st.expander("🤖 呼叫 AI 名师解答"):
                        if st.button("🚀 运行 AI 详细推导", key=f"p1_ai_btn_{q.id}_{q_idx}_{current_subject.value}"):
                            with st.spinner("AI 名师正在严密演算推导..."):
                                box = st.empty()
                                res_text = ""
                                for chunk in ai_t.solve_question_stream(q):
                                    res_text += chunk
                                    box.markdown(res_text)

                q_idx += 1

        # 题目下方按需导出 PDF 专区
        st.markdown("---")
        st.markdown("### 📥 导出与归档试卷 PDF")

        q_ids_tuple = tuple(q.id for q in active_paper.questions)
        tb1, tb2, tb3, tb4 = st.columns(4)

        with tb1:
            st.download_button(
                "📥 下载真题版 PDF",
                data=get_cached_pdf(
                    active_paper.paper_id, active_paper.title, q_ids_tuple, edition_str=PDFEdition.REAL_EXAM.value, subject_str=current_subject.value
                ),
                file_name=f"{active_paper.paper_id}_真题版试卷.pdf",
                mime="application/pdf",
                use_container_width=True,
                key=f"p1_down_real_{active_paper.paper_id}",
            )

        with tb2:
            st.download_button(
                "📝 下载 A4 做题本 PDF",
                data=get_cached_pdf(
                    active_paper.paper_id, active_paper.title, q_ids_tuple, edition_str=PDFEdition.WORKBOOK_A4.value, subject_str=current_subject.value
                ),
                file_name=f"{active_paper.paper_id}_A4做题本.pdf",
                mime="application/pdf",
                use_container_width=True,
                key=f"p1_down_wb_{active_paper.paper_id}",
            )

        with tb3:
            st.download_button(
                "📑 下载详细解析版 PDF",
                data=get_cached_pdf(
                    active_paper.paper_id, active_paper.title, q_ids_tuple, edition_str=PDFEdition.SOLUTION.value, subject_str=current_subject.value
                ),
                file_name=f"{active_paper.paper_id}_详细解析.pdf",
                mime="application/pdf",
                use_container_width=True,
                key=f"p1_down_sol_{active_paper.paper_id}",
            )

        with tb4:
            # 归档写的是"服务器本地磁盘"：云端硬盘临时、多用户共用、用户也拿不到 → 仅本地部署有意义
            if IS_CLOUD:
                st.caption("💡 云端无本地归档，请用左侧下载按钮直接存到你的设备。")
            elif st.button("💾 归档到本地试卷库", use_container_width=True, key=f"p1_archive_btn_{active_paper.paper_id}"):
                with st.spinner("正在生成并归档 3 种版式 PDF..."):
                    real_pdf = get_cached_pdf(active_paper.paper_id, active_paper.title, q_ids_tuple, edition_str=PDFEdition.REAL_EXAM.value, subject_str=current_subject.value)
                    wb_pdf = get_cached_pdf(active_paper.paper_id, active_paper.title, q_ids_tuple, edition_str=PDFEdition.WORKBOOK_A4.value, subject_str=current_subject.value)
                    sol_pdf = get_cached_pdf(active_paper.paper_id, active_paper.title, q_ids_tuple, edition_str=PDFEdition.SOLUTION.value, subject_str=current_subject.value)
                    p_dir = Path("试卷库")
                    p_dir.mkdir(exist_ok=True)
                    (p_dir / f"{active_paper.paper_id}_真题版试卷.pdf").write_bytes(real_pdf)
                    (p_dir / f"{active_paper.paper_id}_A4做题本.pdf").write_bytes(wb_pdf)
                    (p_dir / f"{active_paper.paper_id}_详细解析.pdf").write_bytes(sol_pdf)
                    st.success("✓ 已成功归档 3 种版式 PDF 至 `试卷库/` 文件夹！")


# -------------------------------------------------------------------------
# WORKSPACE 2: 题库逐题标错中枢
# -------------------------------------------------------------------------
with tab_marker_hub:
    # 1. 顶部标错书籍选择 (让不同的书来标记)
    available_target_books = selected_books if selected_books else available_books
    m_top_c1, m_top_c2 = st.columns([1.5, 3.5])
    with m_top_c1:
        target_book = st.selectbox(
            "选择标错书籍",
            options=available_target_books,
            index=0,
            key=f"p2_target_book_{current_subject.value}",
            help="选择需要逐题打标错题的参考书籍",
        )
    with m_top_c2:
        st.caption(f"当前正在标错：《{target_book}》 · {current_subject.value}。在各章节中找到做错的题目并打标，系统会自动收录入错题池用于智能拼卷重练。")

    # 当前书籍对应的题目与真实章节划分
    book_questions = [q for q in raw_questions if getattr(q, "book", "880") == target_book]
    seen_b_ch = set()
    book_chapters = []
    for q in book_questions:
        if q.chapter and q.chapter not in seen_b_ch:
            seen_b_ch.add(q.chapter)
            book_chapters.append(q.chapter)
    if not book_chapters:
        book_chapters = loaded_chapters

    # Filters
    m_col1, m_col2, m_col3, m_col4 = st.columns([1.8, 1, 1, 1.2])
    with m_col1:
        target_ch = st.selectbox(
            "选择章节",
            options=book_chapters,
            index=0,
            key=f"p2_ch_select_{current_subject.value}_{target_book}",
        )
    with m_col2:
        target_diff = st.selectbox("难度分层", options=["全部", "基础题", "综合题", "拓展题"], index=0, key=f"p2_diff_select_{current_subject.value}")
    with m_col3:
        target_type = st.selectbox("题型筛选", options=["全部", "选择题", "填空题", "解答题"], index=0, key=f"p2_type_select_{current_subject.value}")
    with m_col4:
        target_status = st.selectbox("错题状态", options=["全部题目", "🎯 仅看待练错题", "🏆 仅看历史错题", "🔥 仅看顽固错题", "⭐ 仅看所有曾错题", "✅ 仅看未错题"], index=0, key=f"p2_status_select_{current_subject.value}")

    # 本章多维统计指示条
    all_ch_qs = [q for q in book_questions if q.chapter == target_ch]
    ch_active_n = sum(1 for q in all_ch_qs if state_mgr.is_in_active_pool(q.id))
    ch_stubborn_n = sum(1 for q in all_ch_qs if state_mgr.is_in_active_pool(q.id) and state_mgr.get_wrong_count(q.id) >= 2)
    ch_past_n = sum(1 for q in all_ch_qs if state_mgr.is_temporarily_mastered(q.id))

    ch_stats_html = (
        f'<div style="display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:8px 0 12px 0; padding:8px 12px; background:#f8fafc; border-radius:8px; border:1px solid #e2e8f0;">'
        f'<span style="font-weight:700; color:#1e293b;">📖 《{target_book}》{target_ch} · 共 {len(all_ch_qs)} 题</span>'
        f'<span class="badge badge-adv" style="font-weight:700;">🎯 待练错题: {ch_active_n} 题</span>'
        f'<span class="badge" style="background:#fef3c7; color:#92400e; border:1px solid #fcd34d; font-weight:700;">🏆 历史错题: {ch_past_n} 题</span>'
        f'<span class="badge" style="background:#fff1f2; color:#be123c; border:1px solid #fda4af; font-weight:700;">🔥 顽固错题: {ch_stubborn_n} 题</span>'
        f'</div>'
    )
    st.markdown(ch_stats_html, unsafe_allow_html=True)

    # Filtered Questions (严格按 基础题 -> 综合题 -> 拓展题 排序)
    diff_order_list = (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED)
    
    if target_status == "🎯 仅看待练错题":
        status_check = lambda q: state_mgr.is_in_active_pool(q.id)
    elif target_status == "🏆 仅看历史错题":
        status_check = lambda q: state_mgr.is_temporarily_mastered(q.id)
    elif target_status == "🔥 仅看顽固错题":
        status_check = lambda q: state_mgr.is_in_active_pool(q.id) and state_mgr.get_wrong_count(q.id) >= 2
    elif target_status == "⭐ 仅看所有曾错题":
        status_check = lambda q: state_mgr.is_wrong_marked(q.id)
    elif target_status == "✅ 仅看未错题":
        status_check = lambda q: not state_mgr.is_wrong_marked(q.id)
    else:
        status_check = lambda q: True

    ch_questions = [
        q for q in book_questions
        if q.chapter == target_ch
        and (target_diff == "全部" or target_diff in q.difficulty.value)
        and (target_type == "全部" or target_type == q.question_type.value)
        and status_check(q)
    ]
    ch_questions.sort(key=lambda q: (
        diff_order_list.index(q.difficulty) if q.difficulty in diff_order_list else 9,
        (QuestionType.CHOICE, QuestionType.FILL_BLANK, QuestionType.SOLUTION).index(q.question_type) if q.question_type in (QuestionType.CHOICE, QuestionType.FILL_BLANK, QuestionType.SOLUTION) else 9,
        q.id,
    ))

    # 本章全部题目(不受上方难度/题型/状态筛选影响),用于批量标错的题号匹配
    chapter_all = [q for q in book_questions if q.chapter == target_ch]
    _SEC_SHORT = {DifficultyLevel.BASIC: "基础", DifficultyLevel.COMPREHENSIVE: "综合", DifficultyLevel.ADVANCED: "拓展"}
    _TYPE_SHORT = {QuestionType.CHOICE: "选", QuestionType.FILL_BLANK: "填", QuestionType.SOLUTION: "解"}
    _TYPE_LABEL = {"选": "选择", "填": "填空", "解": "解答"}
    _SEC_ICON = {"基础": "🟢 基础篇", "综合": "🔵 综合篇", "拓展": "🟣 拓展篇"}
    # 本章实际存在的 (篇, 题型) 组合及其题目 —— 决定网格显示哪些输入框
    combos: dict[tuple[str, str], list] = {}
    for q in chapter_all:
        combos.setdefault((_SEC_SHORT.get(q.difficulty, "综合"), _TYPE_SHORT.get(q.question_type, "选")), []).append(q)

    def _resolve_ids(inputs: dict[tuple[str, str], str]) -> list[str]:
        """把各 (篇,题型) 框里的题号解析成精确题目 ID(章-篇-题型-序号)。"""
        ids: list[str] = []
        for (sec, typ), text in inputs.items():
            present = {int(q.id.split("-")[3]): q.id for q in combos.get((sec, typ), []) if q.id.split("-")[3].isdigit()}
            for n in re.findall(r"\d+", text or ""):
                qid = present.get(int(n))
                if qid:
                    ids.append(qid)
        return ids

    # Quick Batch Marker Box & Export
    with st.expander("⚡ 批量标错与数据导出", expanded=True):
        st.markdown("刷完一章后，按 **篇 × 题型** 分别输入原书题号（每个题型各自从 1 编号），用逗号或空格隔开：")
        batch_inputs: dict[tuple[str, str], str] = {}
        for sec in ("基础", "综合", "拓展"):
            sec_types = [t for t in ("选", "填", "解") if (sec, t) in combos]
            if not sec_types:
                continue
            st.markdown(f"**{_SEC_ICON[sec]}**")
            cols = st.columns(len(sec_types))
            for col, typ in zip(cols, sec_types):
                with col:
                    n_q = len(combos[(sec, typ)])
                    batch_inputs[(sec, typ)] = st.text_input(
                        f"{_TYPE_LABEL[typ]}题（1-{n_q}）",
                        placeholder="如: 1, 3, 5",
                        # key 含章节：切章节即换一组全新空框，不残留上一章敲的题号
                        key=f"p2_in_{sec}_{typ}_{current_subject.value}_{target_ch}",
                    )

        b_c1, b_c2, b_c3 = st.columns(3)
        with b_c1:
            if st.button("➕ 批量标记错题", type="primary", use_container_width=True, key=f"p2_batch_add_{current_subject.value}"):
                to_mark_ids = _resolve_ids(batch_inputs)
                if to_mark_ids:
                    state_mgr.batch_mark_wrong(to_mark_ids)
                    st.success(f"✓ 成功标记 {len(to_mark_ids)} 道错题！")
                    st.rerun()
                else:
                    st.warning("未匹配到有效题号，请检查输入的数字。")
        with b_c2:
            if st.button("🧹 批量移除错题", use_container_width=True, key=f"p2_batch_remove_{current_subject.value}"):
                to_unmark_ids = _resolve_ids(batch_inputs)
                if to_unmark_ids:
                    state_mgr.batch_unmark_wrong(to_unmark_ids)
                    st.success(f"✓ 成功移除 {len(to_unmark_ids)} 道题目！")
                    st.rerun()
        with b_c3:
            wrong_json = state_mgr.export_wrong_questions_json()
            st.download_button(
                f"📥 导出错题本备份",
                data=wrong_json.encode("utf-8"),
                file_name=f"我的880_{current_subject.value}_错题本备份.json",
                mime="application/json",
                use_container_width=True,
                key=f"p2_down_json_{current_subject.value}",
            )

        st.markdown("---")
        st.markdown("**📤 导入错题本备份**：上传此前导出的 JSON，跨设备 / 跨版本恢复错题（当前题库已不存在的题号会自动跳过）。")
        imp_c1, imp_c2 = st.columns([3, 1.4])
        with imp_c1:
            uploaded_backup = st.file_uploader(
                "选择错题本备份 JSON",
                type=["json"],
                key=f"p2_import_file_{current_subject.value}",
                label_visibility="collapsed",
            )
        with imp_c2:
            import_merge = st.checkbox("合并到现有", value=True, key=f"p2_import_merge_{current_subject.value}", help="勾选=与当前错题合并；取消=先清空再导入")
        if uploaded_backup is not None:
            if st.button("📤 确认导入", type="primary", use_container_width=True, key=f"p2_import_btn_{current_subject.value}"):
                try:
                    raw = uploaded_backup.getvalue().decode("utf-8")
                    valid_ids = {q.id for q in raw_questions}
                    imported, skipped = state_mgr.import_wrong_questions_json(raw, valid_ids=valid_ids, merge=import_merge)
                    msg = f"✓ 成功导入 {imported} 道错题！"
                    if skipped:
                        msg += f" {skipped} 道因当前题库无此题号被跳过。"
                    st.success(msg)
                    st.rerun()
                except Exception as e:
                    st.error(f"导入失败：备份文件格式不正确（{e}）")

    # 分页控制器 (大幅减少组件渲染数量，消除 WebSocket 拥堵)
    total_q_count = len(ch_questions)
    if total_q_count > 25:
        pg_c1, pg_c2 = st.columns([1.5, 3.5])
        with pg_c1:
            page_size_str = st.selectbox("每页展示题数", ["25 题 (极速流畅)", "50 题", "全部展示"], index=0, key=f"p2_pagesize_{current_subject.value}")
        
        if page_size_str.startswith("25"):
            page_size = 25
        elif page_size_str.startswith("50"):
            page_size = 50
        else:
            page_size = total_q_count

        total_pages = max(1, (total_q_count + page_size - 1) // page_size)
        with pg_c2:
            current_page = st.number_input(f"当前页码 (共 {total_pages} 页 · {total_q_count} 题)", min_value=1, max_value=total_pages, value=1, step=1, key=f"p2_page_{current_subject.value}")
        
        start_idx = (current_page - 1) * page_size
        end_idx = min(total_q_count, start_idx + page_size)
        display_questions = ch_questions[start_idx:end_idx]
    else:
        display_questions = ch_questions

    # Question Cards List in Chapter (按 篇 -> 题型 分组展示,题号取 ID 第4段=原书题型内序号)
    st.markdown(f"#### 📖 {target_ch} · 共 {len(ch_questions)} 题")

    _SEC_ORDER = [(DifficultyLevel.BASIC, "🟢 基础篇"), (DifficultyLevel.COMPREHENSIVE, "🔵 综合篇"), (DifficultyLevel.ADVANCED, "🟣 拓展篇")]
    _TYPE_ORDER = [(QuestionType.CHOICE, "选择题"), (QuestionType.FILL_BLANK, "填空题"), (QuestionType.SOLUTION, "解答题")]

    def _seq_of(qid: str) -> int:
        parts = qid.split("-")
        return int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0

    sections_to_show = []
    for diff, sec_icon in _SEC_ORDER:
        for qtype, type_label in _TYPE_ORDER:
            grp = [q for q in display_questions if q.difficulty == diff and q.question_type == qtype]
            if grp:
                sections_to_show.append((f"{sec_icon} · {type_label}", grp))

    for sec_title, sec_q_list in sections_to_show:
        # 总数/已标错取本章该 篇·题型 的全量(chapter_all),不受分页与状态筛选影响
        diff0, qtype0 = sec_q_list[0].difficulty, sec_q_list[0].question_type
        full_group = [q for q in chapter_all if q.difficulty == diff0 and q.question_type == qtype0]
        sec_total = len(full_group)
        sec_wrong_n = sum(1 for q in full_group if state_mgr.is_wrong_marked(q.id))
        st.markdown(f"##### {sec_title} · 共 {sec_total} 题 · 已标错 {sec_wrong_n} 题")

        for q in sec_q_list:
            q_idx_in_sec = _seq_of(q.id)
            is_active = state_mgr.is_in_active_pool(q.id)
            is_temp_mastered = state_mgr.is_temporarily_mastered(q.id)
            w_cnt = state_mgr.get_wrong_count(q.id)
            diff_cls = "badge-basic" if q.difficulty == DifficultyLevel.BASIC else ("badge-adv" if q.difficulty == DifficultyLevel.ADVANCED else "badge-comp")

            with st.container(border=True):
                # Header Row with integrated top-right toggle & count buttons
                if is_active:
                    th1, th2, th3 = st.columns([3.8, 1.4, 0.6])
                    with th1:
                        w2_header_html = (
                            f'<div style="display:flex; align-items:center; margin-top:2px;">'
                            f'<span style="font-weight:800; font-size:15px; color:#000000; margin-right:4px;">{q_idx_in_sec}.</span>'
                            f'</div>'
                        )
                        st.markdown(w2_header_html, unsafe_allow_html=True)
                    with th2:
                        st.button("❌ 移入历史错题", key=f"p2_arch_{q.id}_{current_subject.value}", type="primary", use_container_width=True, help="做题已掌握？点击移入历史错题档案（保留做错次数，不再强制抽取）", on_click=cb_archive_to_history, args=(q.id,))
                    with th3:
                        st.button("➕1", key=f"p2_inc_{q.id}_{current_subject.value}", use_container_width=True, help="又做错了？点击做错次数+1", on_click=cb_inc_wrong, args=(q.id, 1))

                elif is_temp_mastered:
                    th1, th2, th3 = st.columns([3.8, 1.4, 0.9])
                    with th1:
                        w2_header_html = (
                            f'<div style="display:flex; align-items:center; margin-top:2px;">'
                            f'<span style="font-weight:800; font-size:15px; color:#000000; margin-right:4px;">{q_idx_in_sec}.</span>'
                            f'</div>'
                        )
                        st.markdown(w2_header_html, unsafe_allow_html=True)
                    with th2:
                        st.button("🎯 放回待练池", key=f"p2_react_{q.id}_{current_subject.value}", type="primary", use_container_width=True, help="点击重新放回活跃错题池参与组卷抽题", on_click=cb_reactivate_wrong, args=(q.id,))
                    with th3:
                        st.button("🗑️ 彻底删除", key=f"p2_del_{q.id}_{current_subject.value}", use_container_width=True, help="彻底从错题记录中移除", on_click=cb_remove_wrong, args=(q.id,))

                else:
                    th1, th2 = st.columns([4.4, 1.2])
                    with th1:
                        w2_header_html = (
                            f'<div style="display:flex; align-items:center; margin-top:2px;">'
                            f'<span style="font-weight:800; font-size:15px; color:#000000; margin-right:4px;">{q_idx_in_sec}.</span>'
                            f'</div>'
                        )
                        st.markdown(w2_header_html, unsafe_allow_html=True)
                    with th2:
                        st.button("○ 标为错题", key=f"p2_toggle_{q.id}_{current_subject.value}", use_container_width=True, help="做错了？点击放入待练错题池", on_click=cb_toggle_wrong, args=(q.id,))

                # 内联图片走 st.image,文字/公式/表格走 markdown
                render_stem(q.stem)
                if q.options:
                    mc1, mc2 = st.columns(2)
                    for oi, opt in enumerate(q.options):
                        if oi % 2 == 0:
                            with mc1: st.markdown(opt)
                        else:
                            with mc2: st.markdown(opt)

                with st.expander("查看答案与解析"):
                    tags_html = "".join(f'<span class="badge badge-tag">#{t}</span>' for t in q.tags) if q.tags else ""
                    if is_active:
                        if w_cnt >= 2:
                            status_badge = f'<span class="badge" style="background:#fff1f2; color:#be123c; border:1px solid #fda4af; font-weight:700;">🔥 顽固错题 · 累计做错 {w_cnt} 次</span>'
                        else:
                            status_badge = f'<span class="badge badge-adv" style="font-weight:700;">🎯 待练错题 · 累计做错 {w_cnt} 次</span>'
                    elif is_temp_mastered:
                        status_badge = f'<span class="badge" style="background:#fef3c7; color:#92400e; border:1px solid #fcd34d; font-weight:700;">🏆 历史错题 · 历史做错 {w_cnt} 次</span>'
                    else:
                        status_badge = ''

                    meta_tags_row = (
                        f'<div style="display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:8px;">'
                        f'<span class="badge badge-ch">《{getattr(q, "book", "880")}》</span>'
                        f'<span class="badge {diff_cls}">[{q.difficulty.value}]</span>'
                        f'<span class="badge badge-ch">{q.chapter}</span>'
                        f'<span class="badge badge-ch">{q.question_type.value}</span>'
                        f'<span style="font-size:11.5px; color:#64748b; font-family:monospace; margin-right:4px;">ID: {q.id}</span>'
                        f'{tags_html} {status_badge}'
                        f'</div>'
                    )
                    st.markdown(meta_tags_row, unsafe_allow_html=True)
                    if q.answer: st.markdown(f"**【参考答案】**：`{q.answer}`")
                    if q.solution: st.markdown(f"**【详细解析】**：\n{q.solution}")


# -------------------------------------------------------------------------
# WORKSPACE 3: 全科考点覆盖与错题画像 (进度雷达)
# -------------------------------------------------------------------------
with tab_coverage_hub:
    st.markdown(f"### 📈 {current_books_str} · {current_subject.value} 考点覆盖与错题画像")

    cov_chapters = state_mgr.historical_covered_chapters & default_target_chapters
    total_target_n = max(1, len(default_target_chapters))
    cov_ratio_val = len(cov_chapters) / total_target_n

    # Top Metrics Grid
    c_m1, c_m2, c_m3, c_m4 = st.columns(4)
    with c_m1: st.metric("🎯 待练错题", f"{subject_wrong_count} 题")
    with c_m2: st.metric("🏆 历史错题", f"{past_wrong_count} 题")
    with c_m3: st.metric("🔥 顽固错题", f"{repeated_wrong_count} 题")
    with c_m4: st.metric("📊 考点覆盖率", f"{cov_ratio_val * 100:.1f}%")

    st.markdown(
        f"""
        <div class="glass-card" style="background:linear-gradient(135deg, #f0fdf4 0%, #ffffff 100%); border:1px solid #bbf7d0; margin-top:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <span style="font-size:15px; font-weight:800; color:#166534;">🎯 章节覆盖进度</span>
                <span style="font-size:16px; font-weight:900; color:#059669;">{cov_ratio_val * 100:.1f}% · {len(cov_chapters)} / {total_target_n} 章节</span>
            </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress(min(1.0, cov_ratio_val))

    # Badge Pill Matrix
    p_html = []
    for ch in loaded_chapters:
        is_c = ch in cov_chapters
        ch_wrong_n = sum(1 for q in subject_wrong_pool if q.chapter == ch)
        ch_stubb_n = sum(1 for q in subject_wrong_pool if q.chapter == ch and state_mgr.get_wrong_count(q.id) >= 2)
        cls_name = "radar-pill-done" if is_c else "radar-pill-todo"
        sym = "✓ " if is_c else "○ "
        wrong_str = ""
        if ch_wrong_n > 0:
            stubb_str = f" · 🔥{ch_stubb_n}" if ch_stubb_n > 0 else ""
            wrong_str = f" · 错{ch_wrong_n}{stubb_str}"
        p_html.append(f'<span class="radar-pill {cls_name}">{sym}{ch}{wrong_str}</span>')

    st.markdown("".join(p_html) + "</div>", unsafe_allow_html=True)

    # 顽固错题重点攻坚清单
    stubborn_qs = [q for q in subject_active_wrong_pool if state_mgr.get_wrong_count(q.id) >= 2]
    stubborn_qs.sort(key=lambda q: state_mgr.get_wrong_count(q.id), reverse=True)
    if stubborn_qs:
        with st.expander(f"🔥 本科目共 {len(stubborn_qs)} 道高频顽固错题重点攻坚清单", expanded=True):
            for sq in stubborn_qs:
                cnt = state_mgr.get_wrong_count(sq.id)
                tags_s = " ".join(f"#{t}" for t in sq.tags[:2])
                sq_row_html = (
                    f'<div style="display:flex; justify-content:space-between; align-items:center; padding:6px 10px; margin-bottom:6px; background:#fff1f2; border:1px solid #fda4af; border-radius:6px;">'
                    f'<div>'
                    f'<span style="font-weight:800; color:#be123c; font-family:monospace; margin-right:8px;">{sq.id}</span>'
                    f'<span style="font-size:12px; color:#475569; margin-right:8px;">[{sq.chapter}] [{sq.difficulty.value}]</span>'
                    f'<span style="font-size:11.5px; color:#64748b;">{tags_s}</span>'
                    f'</div>'
                    f'<span class="badge" style="background:#be123c; color:#ffffff; font-weight:800;">做错 {cnt} 次</span>'
                    f'</div>'
                )
                st.markdown(sq_row_html, unsafe_allow_html=True)

    # Category Breakdowns
    s_c1, s_c2, s_c3 = st.columns(3)
    with s_c1:
        st.markdown("##### 📐 高等数学")
        adv_chs = [c for c in loaded_chapters if any(q.chapter == c and q.category == ChapterCategory.ADVANCED_MATH for q in all_questions)]
        adv_cov = [c for c in adv_chs if c in cov_chapters]
        st.markdown(f"**覆盖进度**：`{len(adv_cov)} / {len(adv_chs)}` 章节")
        for ch in adv_chs:
            ch_w = sum(1 for q in subject_wrong_pool if q.chapter == ch)
            ch_st = sum(1 for q in subject_wrong_pool if q.chapter == ch and state_mgr.get_wrong_count(q.id) >= 2)
            st_text = f" · 🔥顽固{ch_st}" if ch_st > 0 else ""
            w_tag = f" <span style='color:#e11d48; font-size:12px;'>[错{ch_w}题{st_text}]</span>" if ch_w > 0 else ""
            st.markdown(f"{'✅' if ch in cov_chapters else '⏳'} {ch}{w_tag}", unsafe_allow_html=True)

    with s_c2:
        st.markdown("##### 🔢 线性代数")
        lin_chs = [c for c in loaded_chapters if any(q.chapter == c and q.category == ChapterCategory.LINEAR_ALGEBRA for q in all_questions)]
        lin_cov = [c for c in lin_chs if c in cov_chapters]
        st.markdown(f"**覆盖进度**：`{len(lin_cov)} / {len(lin_chs)}` 章节")
        for ch in lin_chs:
            ch_w = sum(1 for q in subject_wrong_pool if q.chapter == ch)
            ch_st = sum(1 for q in subject_wrong_pool if q.chapter == ch and state_mgr.get_wrong_count(q.id) >= 2)
            st_text = f" · 🔥顽固{ch_st}" if ch_st > 0 else ""
            w_tag = f" <span style='color:#e11d48; font-size:12px;'>[错{ch_w}题{st_text}]</span>" if ch_w > 0 else ""
            st.markdown(f"{'✅' if ch in cov_chapters else '⏳'} {ch}{w_tag}", unsafe_allow_html=True)

    with s_c3:
        st.markdown("##### 🎲 概率论与数理统计")
        prob_chs = [c for c in loaded_chapters if any(q.chapter == c and q.category == ChapterCategory.PROBABILITY for q in all_questions)]
        if not prob_chs:
            st.info("本科目不考概率统计")
        else:
            prob_cov = [c for c in prob_chs if c in cov_chapters]
            st.markdown(f"**覆盖进度**：`{len(prob_cov)} / {len(prob_chs)}` 章节")
            for ch in prob_chs:
                ch_w = sum(1 for q in subject_wrong_pool if q.chapter == ch)
                ch_st = sum(1 for q in subject_wrong_pool if q.chapter == ch and state_mgr.get_wrong_count(q.id) >= 2)
                st_text = f" · 🔥顽固{ch_st}" if ch_st > 0 else ""
                w_tag = f" <span style='color:#e11d48; font-size:12px;'>[错{ch_w}题{st_text}]</span>" if ch_w > 0 else ""
                st.markdown(f"{'✅' if ch in cov_chapters else '⏳'} {ch}{w_tag}", unsafe_allow_html=True)


# =========================================================================
# 7. URL 错题码同步（把当前科目错题状态写回网址，保持链接可跨设备恢复）
# =========================================================================
if url_data_key and current_subject != SubjectType.CUSTOM:
    latest_code = state_mgr.to_url_code(canonical_ids)
    # 仅在真正变化时写入，避免无谓 rerun
    if st.query_params.get(url_data_key) != latest_code:
        st.query_params[url_data_key] = latest_code
    # seen 码(已抽过题)写回 n1/n2/n3,与错题码独立
    if url_seen_key:
        seen_code = state_mgr.seen_to_url_code(canonical_ids)
        if st.query_params.get(url_seen_key) != seen_code:
            st.query_params[url_seen_key] = seen_code

# 试卷码同步：把当前生成的试卷题号写回网址（q1/q2/q3），做完后可凭链接查阅答案
if paper_url_key and current_subject != SubjectType.CUSTOM:
    _cur_bundle = st.session_state.get("current_bundle_p1")
    _cur_paper = st.session_state.get("current_paper_p1")
    _papers_qids = None
    if _cur_bundle:
        _papers_qids = [[q.id for q in p.questions] for p in _cur_bundle.papers]
    elif _cur_paper:
        _papers_qids = [[q.id for q in _cur_paper.questions]]
    if _papers_qids:
        _pcode = StateManager.encode_papers_code(_papers_qids, canonical_ids)
        if st.query_params.get(paper_url_key) != _pcode:
            st.query_params[paper_url_key] = _pcode

# AI 配置同步：仅 Base URL 与 Model 进网址，API Key 严禁写入
_ai_url = st.session_state.get("ai_base_url", "")
_ai_model = st.session_state.get("ai_model", "")
if _ai_url and st.query_params.get("au") != _ai_url:
    st.query_params["au"] = _ai_url
if _ai_model and st.query_params.get("am") != _ai_model:
    st.query_params["am"] = _ai_model


# =========================================================================
# 8. Academic Footer
# =========================================================================
st.markdown(
    f"""
    <div style="text-align:center; color:#94a3b8; font-size:12px; margin-top:50px; padding:24px 0; border-top:1px solid #e2e8f0;">
        考研拼好卷系统 · 当前书籍: {current_books_str} · 当前科目: {current_subject.value} · {len(loaded_chapters)} 章 · {len(all_questions)} 题
    </div>
    """,
    unsafe_allow_html=True,
)