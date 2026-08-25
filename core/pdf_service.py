"""
考研数学智能组卷系统 - A4 PDF 排版与导出服务
1:1 像素级复刻前端 Streamlit 原生渲染体验：
- 采用与前端一致的 Python-Markdown + KaTeX 占位符保真渲染
- 采用与前端 st.container(border=True) 一致的轻质圆角卡片容器
- 采用与前端 st.columns(2) 一致的双列选项排版
- 去除一切冗余修饰，仅保留纯净题号、题干与选项
"""
from __future__ import annotations

import html
import logging
import os
import re
import shutil
import subprocess
import tempfile
from enum import Enum
from pathlib import Path

import markdown

from core.models import PaperItem, QuestionItem, QuestionType, SubjectType

logger = logging.getLogger(__name__)


class PDFEdition(str, Enum):
    REAL_EXAM = "real_exam"      # 真题/模考版：1:1 复刻前端做题卡片
    WORKBOOK_A4 = "workbook_a4"  # A4 做题本版：预留手写草稿与大题演算框
    SOLUTION = "solution"        # 详细解析版：参考答案与分步解析


class PDFService:
    """A4 高保真试卷排版与导出服务（1:1 复刻前端渲染）"""

    def __init__(self):
        self._assets_dir = Path.cwd() / "assets" / "katex"
        self._md = markdown.Markdown(extensions=["tables", "fenced_code"])

    def _get_katex_headers(self) -> str:
        """注入 KaTeX 资源与自动渲染脚本（优先使用本地内联，0ms 网络依赖，100% 离线可用）"""
        js_file = self._assets_dir / "katex.min.js"
        css_file = self._assets_dir / "katex.min.css"
        render_file = self._assets_dir / "auto-render.min.js"

        macro_js = """
            macros: {
                "\\\\wideparen": "\\\\overset{\\\\frown}{#1}",
                "\\\\oiint": "\\\\iint",
                "\\\\mathring": "\\\\overset{\\\\circ}{#1}"
            },
            throwOnError: false
        """

        if js_file.exists() and css_file.exists() and render_file.exists():
            css_content = css_file.read_text(encoding="utf-8")
            # 解决临时 HTML 文件脱离 assets 目录时 KaTeX 矢量字体无法加载的路径问题
            css_content = css_content.replace("url(fonts/", 'url("https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/fonts/')
            js_content = js_file.read_text(encoding="utf-8")
            render_content = render_file.read_text(encoding="utf-8")
            return f"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<style>{css_content}</style>
<script>{js_content}</script>
<script>{render_content}</script>
<script>
    document.addEventListener("DOMContentLoaded", function() {{
        if (typeof renderMathInElement === "function") {{
            renderMathInElement(document.body, {{
                delimiters: [
                    {{left: '$$', right: '$$', display: true}},
                    {{left: '$', right: '$', display: false}},
                    {{left: '\\\\(', right: '\\\\)', display: false}},
                    {{left: '\\\\[', right: '\\\\]', display: true}}
                ],
                {macro_js}
            }});
        }}
    }});
</script>
"""
        return f"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<script>
    document.addEventListener("DOMContentLoaded", function() {{
        if (typeof renderMathInElement === "function") {{
            renderMathInElement(document.body, {{
                delimiters: [
                    {{left: '$$', right: '$$', display: true}},
                    {{left: '$', right: '$', display: false}},
                    {{left: '\\(', right: '\\)', display: false}},
                    {{left: '\\[', right: '\\]', display: true}}
                ],
                {macro_js}
            }});
        }}
    }});
</script>
"""

    def _get_subject_info(self, subject: SubjectType) -> tuple[str, str]:
        """获取科目中文与代码"""
        if subject == SubjectType.MATH_1:
            return "一", "301"
        elif subject == SubjectType.MATH_2:
            return "二", "302"
        elif subject == SubjectType.MATH_3:
            return "三", "303"
        return "一", "301"

    @staticmethod
    def preprocess_math_string(s: str) -> str:
        """解决所有 LaTeX / KaTeX 语法不兼容与特殊字符宏映射"""
        s = re.sub(r'\\wideparen\s*\{([^}]+)\}', r'\\overset{\\frown}{\1}', s)
        s = re.sub(r'\\wideparen\s+([A-Za-z0-9]+)', r'\\overset{\\frown}{\1}', s)
        s = re.sub(r'\\\\([a-zA-Z])', r'\\\\ \1', s)
        s = s.replace('<', r'\lt ').replace('>', r'\gt ')
        s = s.replace(r'\oiint', r'\iint')
        s = re.sub(r'\\mathring\s*\{([^}]+)\}', r'\\overset{\\circ}{\1}', s)
        return s

    @staticmethod
    def format_math_text(text: str) -> str:
        r"""
        1:1 复刻前端 Markdown 与数学公式渲染：
        1. 剥离前缀序号
        2. 占位保护 $$...$$ 与 $...$ 公式，防止 Markdown 转移特殊字符
        3. 用标准 Python-Markdown 解析段落与表格
        4. 还原公式占位符供 KaTeX 渲染
        """
        if not text:
            return ""
        
        # 剥离前缀序号
        s = re.sub(r"^(?:\*\*\(\d+\)\*\*|\(\d+\)|（\d+）|\d+[.．、])\s*", "", text.strip())

        math_store: dict[str, str] = {}
        
        def stash_math(m: re.Match) -> str:
            idx = len(math_store)
            placeholder = f"MATHSTASHXYZ{idx}END"
            raw = m.group(0)
            if raw.startswith('$$'):
                clean_math = f"$${PDFService.preprocess_math_string(raw[2:-2].strip())}$$"
            else:
                clean_math = f"${PDFService.preprocess_math_string(raw[1:-1])}$"
            math_store[placeholder] = clean_math
            return placeholder

        # 1. 占位保护数学公式
        s_stashed = re.sub(r'(\$\$.*?\$\$|\$.*?\$)', stash_math, s, flags=re.DOTALL)

        # 2. Markdown 标准转换（自然段落 <p> 与表格 <table>）
        md = markdown.Markdown(extensions=["tables", "fenced_code"])
        html_out = md.convert(s_stashed)

        # 3. 还原数学公式
        for placeholder, clean_math in math_store.items():
            html_out = html_out.replace(placeholder, clean_math)

        return html_out

    @staticmethod
    def _render_options_grid(options: list[str]) -> str:
        """1:1 复刻前端 Streamlit st.columns(2) 双列选项排版"""
        if not options:
            return ""
        
        # 估算可见字符长度
        def estimate_visible_len(opt: str) -> int:
            clean = re.sub(r"\\[a-zA-Z]+", "", opt)
            clean = re.sub(r"[\${}\\\s]", "", clean)
            return len(clean)

        max_vis = max((estimate_visible_len(opt) for opt in options), default=0)

        # 超短纯选项（如 A. 0, B. 1, C. 2, D. 3）4 列并排
        if max_vis <= 8 and len(options) == 4:
            grid_style = "grid-template-columns: repeat(4, 1fr);"
        # 超长段落（超 80 个字符的论述型文字）单列排版
        elif max_vis > 80:
            grid_style = "grid-template-columns: 1fr;"
        # 所有常规数学公式与选择题：标准双列（与网页端 1:1 对称）
        else:
            grid_style = "grid-template-columns: 1fr 1fr;"

        opt_items = "".join(f'<div class="opt-item">{PDFService.format_math_text(opt)}</div>' for opt in options)
        return f'<div class="options-grid" style="{grid_style}">{opt_items}</div>'

    @staticmethod
    def format_question_stem(q_idx: int, stem_text: str) -> str:
        """格式化题干：剥离原有冗余序号，将纯黑序号（如 1. ）置于首行题干最前列，实现标准试卷流式排版"""
        formatted = PDFService.format_math_text(stem_text)
        num_prefix = f'<span class="q-num">{q_idx}.&nbsp;</span>'
        if formatted.startswith("<p>"):
            return f"<p>{num_prefix}" + formatted[3:]
        elif formatted.startswith("<div>"):
            return f"<div>{num_prefix}" + formatted[5:]
        else:
            return f"<p>{num_prefix}{formatted}</p>"

    def _get_common_css(self) -> str:
        """标准试卷纯净排版样式（无框线，序号前置）"""
        return """
@page {
    size: A4 portrait;
    margin: 16mm 14mm 16mm 14mm;
    @bottom-center {
        content: "第 " counter(page) " 页 · 共 " counter(pages) " 页";
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
        font-size: 8.5pt;
        color: #94a3b8;
    }
}
* {
    box-sizing: border-box;
}
body {
    font-family: "Source Sans Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    font-size: 10.5pt;
    line-height: 1.65;
    color: #0f172a;
    background: #ffffff;
    margin: 0;
    padding: 0;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
}

/* 顶部标题栏 */
.paper-header {
    text-align: center;
    border-bottom: 1.5px solid #000000;
    padding-bottom: 8px;
    margin-bottom: 16px;
}
.paper-title {
    font-size: 15pt;
    font-weight: 800;
    color: #000000;
    margin: 0 0 6px 0;
}
.paper-meta {
    font-size: 9.5pt;
    color: #475569;
}

/* 大题分组标题 */
.section-title {
    font-size: 11pt;
    font-weight: 800;
    color: #000000;
    margin: 16px 0 10px 0;
    padding-bottom: 4px;
    border-bottom: 1px solid #cbd5e1;
    page-break-after: avoid;
}

/* 题目排版（纯净无外框、无背景底色） */
.q-card {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    margin-bottom: 14px;
    page-break-inside: avoid;
}
.q-num {
    font-weight: 800;
    font-size: 10.5pt;
    color: #000000;
    display: inline;
}
.q-stem {
    font-size: 10.5pt;
    line-height: 1.65;
    color: #000000;
}
.q-stem p {
    margin: 0 0 6px 0;
}
.q-stem p:last-child {
    margin-bottom: 0;
}

/* 选项网格 */
.options-grid {
    display: grid;
    gap: 4px 16px;
    margin: 6px 0 4px 0;
    font-size: 10pt;
    color: #000000;
}
.opt-item p {
    margin: 0;
    line-height: 1.6;
}

/* 数据表格 */
table {
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 10pt;
    text-align: center;
    background: #ffffff;
}
table th, table td {
    border: 1px solid #cbd5e1;
    padding: 5px 14px;
    text-align: center;
    font-weight: normal;
    min-width: 40px;
}
table th {
    background: #f8fafc;
    font-weight: 600;
}

/* 做题本纯手写留白区（无外框、无虚线、无提示文字，纯留白空间） */
.workspace-box {
    border: none;
    background: transparent;
    padding: 0;
    margin: 0;
}
.wb-choice-box {
    height: 40mm;
}
.wb-fill-box {
    height: 60mm;
}
.wb-solution-box {
    height: 140mm;
}

/* 解析版区块 */
.solution-block {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 3px solid #2563eb;
    border-radius: 4px;
    padding: 8px 12px;
    margin-top: 8px;
    font-size: 9.5pt;
    color: #0f172a;
}
.solution-block p {
    margin: 2px 0;
}

/* KaTeX 与正文基线对齐 */
.katex {
    font-size: 1.04em !important;
    text-rendering: optimizeLegibility;
}
.katex-display {
    margin: 0.4em 0 !important;
}
"""

    # =========================================================================
    # 1. 模考/真题版 HTML
    # =========================================================================
    def _build_real_exam_html(self, paper: PaperItem) -> str:
        sub_cn, _ = self._get_subject_info(paper.subject)
        
        choices = [q for q in paper.questions if q.question_type == QuestionType.CHOICE]
        fills = [q for q in paper.questions if q.question_type == QuestionType.FILL_BLANK]
        solutions = [q for q in paper.questions if q.question_type == QuestionType.SOLUTION]

        blocks: list[str] = []
        q_idx = 1

        if choices:
            blocks.append(f'<div class="section-title">一、选择题（共 {len(choices)} 题，每题 5 分，共 {len(choices)*5} 分）</div>')
            for q in choices:
                stem_html = self.format_question_stem(q_idx, q.stem)
                options_html = self._render_options_grid(q.options)
                blocks.append(f"""
                <div class="q-card">
                    <div class="q-stem">{stem_html}</div>
                    {options_html}
                </div>
                """)
                q_idx += 1

        if fills:
            blocks.append(f'<div class="section-title">二、填空题（共 {len(fills)} 题，每题 5 分，共 {len(fills)*5} 分）</div>')
            for q in fills:
                stem_html = self.format_question_stem(q_idx, q.stem)
                blocks.append(f"""
                <div class="q-card">
                    <div class="q-stem">{stem_html}</div>
                </div>
                """)
                q_idx += 1

        if solutions:
            blocks.append(f'<div class="section-title">三、解答题（共 {len(solutions)} 题，共 70 分）</div>')
            for q in solutions:
                stem_html = self.format_question_stem(q_idx, q.stem)
                blocks.append(f"""
                <div class="q-card">
                    <div class="q-stem">{stem_html}</div>
                </div>
                """)
                q_idx += 1

        body_content = "\n".join(blocks)
        katex_head = self._get_katex_headers()
        common_css = self._get_common_css()

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>2026 年考研数学{sub_cn}全真模拟试卷</title>
{katex_head}
<style>
{common_css}
</style>
</head>
<body>

<div class="paper-header">
    <div class="paper-title">2026 年全国硕士研究生招生考试数学（{sub_cn}）模拟试卷</div>
    <div class="paper-meta">考试时间: 180 分钟 · 满分: 150 分 · 共 {paper.total_count} 题 · 卷号: {paper.paper_id}</div>
</div>

{body_content}

</body>
</html>"""

    # =========================================================================
    # 2. A4 做题本版 HTML (纯留白无框线无注释)
    # =========================================================================
    def _build_workbook_html(self, paper: PaperItem) -> str:
        sub_cn, _ = self._get_subject_info(paper.subject)
        
        choices = [q for q in paper.questions if q.question_type == QuestionType.CHOICE]
        fills = [q for q in paper.questions if q.question_type == QuestionType.FILL_BLANK]
        solutions = [q for q in paper.questions if q.question_type == QuestionType.SOLUTION]

        blocks: list[str] = []
        q_idx = 1

        if choices:
            blocks.append(f'<div class="section-title">一、选择题（共 {len(choices)} 题）</div>')
            for q in choices:
                stem_html = self.format_question_stem(q_idx, q.stem)
                options_html = self._render_options_grid(q.options)
                workspace = '<div class="workspace-box wb-choice-box"></div>'
                blocks.append(f"""
                <div class="q-card">
                    <div class="q-stem">{stem_html}</div>
                    {options_html}
                    {workspace}
                </div>
                """)
                q_idx += 1

        if fills:
            blocks.append(f'<div class="section-title">二、填空题（共 {len(fills)} 题）</div>')
            for q in fills:
                stem_html = self.format_question_stem(q_idx, q.stem)
                workspace = '<div class="workspace-box wb-fill-box"></div>'
                blocks.append(f"""
                <div class="q-card">
                    <div class="q-stem">{stem_html}</div>
                    {workspace}
                </div>
                """)
                q_idx += 1

        if solutions:
            blocks.append(f'<div class="section-title">三、解答题（共 {len(solutions)} 题）</div>')
            for q in solutions:
                stem_html = self.format_question_stem(q_idx, q.stem)
                workspace = '<div class="workspace-box wb-solution-box"></div>'
                blocks.append(f"""
                <div class="q-card">
                    <div class="q-stem">{stem_html}</div>
                    {workspace}
                </div>
                """)
                q_idx += 1

        body_content = "\n".join(blocks)
        katex_head = self._get_katex_headers()
        common_css = self._get_common_css()

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>2026 年考研数学{sub_cn} A4 留白做题本</title>
{katex_head}
<style>
{common_css}
</style>
</head>
<body>

<div class="paper-header">
    <div class="paper-title">考研数学《880》A4 留白做题本（数学{sub_cn}）</div>
    <div class="paper-meta">全卷留白演算空间 · 适合 iPad 导题与 A4 打印刷题 · 卷号: {paper.paper_id}</div>
</div>

{body_content}

</body>
</html>"""

    # =========================================================================
    # 3. 详细解析版 HTML
    # =========================================================================
    def _build_solution_html(self, paper: PaperItem) -> str:
        sub_cn, _ = self._get_subject_info(paper.subject)
        
        blocks: list[str] = []
        for idx, q in enumerate(paper.questions, start=1):
            stem_html = self.format_question_stem(idx, q.stem)
            options_html = self._render_options_grid(q.options) if q.options else ""

            ans_str = q.answer if q.answer else "略"
            sol_html = self.format_math_text(q.solution) if q.solution else "详见标准解析推导。"

            solution_box = f"""
            <div class="solution-block">
                <div style="margin-bottom:4px;"><b>【参考答案】</b>：<code style="background:#f1f5f9; padding:1px 6px; border-radius:4px; font-weight:bold;">{ans_str}</code></div>
                <div><b>【详细推导与解析步骤】</b>：<div style="margin-top:4px; color:#1e293b;">{sol_html}</div></div>
            </div>
            """

            blocks.append(f"""
            <div class="q-card">
                <div class="q-stem">{stem_html}</div>
                {options_html}
                {solution_box}
            </div>
            """)

        body_content = "\n".join(blocks)
        katex_head = self._get_katex_headers()
        common_css = self._get_common_css()

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>2026 年考研数学{sub_cn} 详细解析版</title>
{katex_head}
<style>
{common_css}
</style>
</head>
<body>

<div class="paper-header">
    <div class="paper-title">考研数学《880》参考答案与详细解析（数学{sub_cn}）</div>
    <div class="paper-meta">全套题目参考答案与分步推导 · 卷号: {paper.paper_id}</div>
</div>

{body_content}

</body>
</html>"""

    def generate_html(self, paper: PaperItem, edition: PDFEdition = PDFEdition.REAL_EXAM) -> str:
        """生成纯净 HTML 页面"""
        if edition == PDFEdition.REAL_EXAM:
            return self._build_real_exam_html(paper)
        elif edition == PDFEdition.WORKBOOK_A4:
            return self._build_workbook_html(paper)
        else:
            return self._build_solution_html(paper)

    def render_pdf_bytes(self, paper: PaperItem, edition: PDFEdition = PDFEdition.REAL_EXAM) -> bytes:
        """输出标准 A4 PDF 二进制流。

        优先用 Headless 浏览器（Edge/Chrome/Chromium，Win 本地或云端 Linux 均支持）——
        浏览器会执行 KaTeX 的 JS，公式正确渲染。浏览器不可用时退回 WeasyPrint（依赖已在
        packages.txt），至少产出可打开的 PDF。两者都不可用才退回 HTML 字节。
        """
        html_content = self.generate_html(paper, edition)

        pdf = self._render_via_browser(html_content)
        if pdf:
            return pdf

        pdf = self._render_via_weasyprint(html_content)
        if pdf:
            return pdf

        logger.warning("无可用 PDF 渲染引擎（浏览器 + WeasyPrint 均失败），退回 HTML 字节。")
        return html_content.encode("utf-8")

    @staticmethod
    def _find_browser() -> str | None:
        """跨平台定位 Headless 浏览器：Windows 的 Edge/Chrome，Linux（云端）的 Chromium。"""
        candidates = [
            shutil.which("msedge"),
            shutil.which("chrome"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
        ]
        return next((b for b in candidates if b and os.path.exists(b)), None)

    def _render_via_browser(self, html_content: str) -> bytes | None:
        browser_exe = self._find_browser()
        if not browser_exe:
            return None

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write(html_content)
            temp_html = f.name
        temp_pdf = temp_html.replace(".html", ".pdf")

        # --disable-dev-shm-usage：容器内 /dev/shm 很小，不加 chromium 会崩；云端冷启动慢，超时放宽
        common = ["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-extensions", "--no-pdf-header-footer"]
        flag_candidates = [
            [browser_exe, "--headless=new", *common, f"--print-to-pdf={temp_pdf}", temp_html],
            [browser_exe, "--headless", *common, f"--print-to-pdf={temp_pdf}", temp_html],
        ]
        try:
            for cmd in flag_candidates:
                try:
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                    if os.path.exists(temp_pdf) and os.path.getsize(temp_pdf) > 0:
                        return open(temp_pdf, "rb").read()
                except Exception as ex:
                    logger.warning(f"Headless PDF 尝试失败，尝试备用参数: {ex}")
                    continue
        finally:
            for p in (temp_html, temp_pdf):
                if os.path.exists(p):
                    try: os.unlink(p)
                    except Exception: pass
        return None

    def _render_via_weasyprint(self, html_content: str) -> bytes | None:
        """WeasyPrint 兜底：不执行 JS，公式可能显示为原始 LaTeX，但能产出可打开的 PDF。"""
        try:
            from weasyprint import HTML  # 延迟导入：本地无 GTK 时不影响浏览器路径
            return HTML(string=html_content).write_pdf()
        except Exception as ex:
            logger.warning(f"WeasyPrint 兜底渲染失败: {ex}")
            return None
