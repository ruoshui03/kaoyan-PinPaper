"""
考研数学智能组卷系统 - 题库数据加载与多维索引服务 (Clean-Room 原创实现)
支持数学一 (23章)、数学二 (12章)、数学三 (21章) 题库全量独立加载与智能路由
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

from core.models import (
    ChapterCategory,
    DifficultyLevel,
    QuestionItem,
    QuestionType,
    SubjectType,
    MATH_1_CHAPTERS,
    MATH_2_CHAPTERS,
    MATH_3_CHAPTERS,
)

logger = logging.getLogger(__name__)


def classify_category(chapter_name: str, chapter_num: int = 1) -> ChapterCategory:
    """根据章节名称或编号准确识别三大学科分类"""
    # 概率论与数理统计
    if any(k in chapter_name for k in ["随机", "概率", "分布", "数字特征", "大数定律", "极限定理", "数理统计", "统计", "参数估计", "假设检验"]):
        return ChapterCategory.PROBABILITY
    # 线性代数
    elif any(k in chapter_name for k in ["矩阵", "向量", "行列式", "方程组", "相似", "二次型"]):
        return ChapterCategory.LINEAR_ALGEBRA
    # 高等数学
    elif any(k in chapter_name for k in ["数学", "微积分", "函数", "极限", "连续", "微分", "导数", "积分", "二重积分", "重积分", "级数", "方程", "空间", "解析几何", "经济"]):
        return ChapterCategory.ADVANCED_MATH
    else:
        if 1 <= chapter_num <= 9:
            return ChapterCategory.ADVANCED_MATH
        elif 10 <= chapter_num <= 15:
            return ChapterCategory.LINEAR_ALGEBRA
        else:
            return ChapterCategory.PROBABILITY


def parse_chapter_number(chapter_str: str, qid: str = "") -> int:
    """解析章节编号"""
    m = re.search(r"^(\d+)", qid)
    if m:
        return int(m.group(1))

    cn_num = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15, "十六": 16, "十七": 17,
        "十八": 18, "十九": 19, "二十": 20, "二十一": 21, "二十二": 22, "二十三": 23,
    }
    for k, v in cn_num.items():
        if f"第{k}章" in chapter_str:
            return v
    return 1


def get_diff_rank(diff_or_str: DifficultyLevel | str) -> int:
    """标准难度层级排序权重：基础题(1) < 综合题(2) < 拓展题(3)"""
    if isinstance(diff_or_str, DifficultyLevel):
        return {DifficultyLevel.BASIC: 1, DifficultyLevel.COMPREHENSIVE: 2, DifficultyLevel.ADVANCED: 3}.get(diff_or_str, 2)
    s = str(diff_or_str)
    if "基础" in s:
        return 1
    elif "综合" in s:
        return 2
    elif "拓展" in s or "拔高" in s:
        return 3
    return 2


def get_type_rank(type_or_str: "QuestionType | str") -> int:
    """题型排序权重:选择题(1) < 填空题(2) < 解答题(3)"""
    s = str(getattr(type_or_str, "value", type_or_str))
    if "选" in s:
        return 1
    if "填" in s:
        return 2
    if "解" in s or "计算" in s or "证明" in s or "大题" in s:
        return 3
    return 1


def parse_qid_tuple(qid: str) -> tuple[int, int, int, int]:
    """将题目 ID 解析为可精准排序的四元组。

    新格式 章-篇-题型-序号(如 03-基础-选-03)→ (章, 篇rank, 题型rank, 序号)。
    旧格式 章-篇-序号(如 03-基础-19)→ (章, 篇rank, 0, 序号),仍可排序,兼容过渡。
    """
    parts = qid.split("-")
    ch_num = int(parts[0]) if parts and parts[0].isdigit() else 99
    diff_rank = get_diff_rank(parts[1]) if len(parts) >= 2 else 2
    if len(parts) >= 4:  # 章-篇-题型-序号
        type_rank = get_type_rank(parts[2])
        q_num = int(parts[3]) if parts[3].isdigit() else 99
    else:                 # 旧三段 章-篇-序号
        type_rank = 0
        q_num = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 99
    return (ch_num, diff_rank, type_rank, q_num)


class BankLoader:
    """高可用题库数据加载器与多维索引服务"""

    def __init__(
        self,
        subject: SubjectType = SubjectType.MATH_1,
        metadata_dir: Path | str | None = None,
        problems_dir: Path | str | None = None,
    ):
        self.subject = subject
        project_root = Path(__file__).resolve().parent.parent
        root = project_root if (project_root / '题库资料').exists() else Path.cwd()

        # 根据科目定位题库目录
        subject_folder_name = "880数学一"
        if subject == SubjectType.MATH_2:
            subject_folder_name = "880数学二"
        elif subject == SubjectType.MATH_3:
            subject_folder_name = "880数学三"

        if metadata_dir and Path(metadata_dir).exists():
            self.metadata_dir = Path(metadata_dir).resolve()
        elif (root / "题库资料" / subject_folder_name / "metadata").exists():
            self.metadata_dir = (root / "题库资料" / subject_folder_name / "metadata").resolve()
        elif (root / "题库资料" / "880数学一" / "metadata").exists():
            self.metadata_dir = (root / "题库资料" / "880数学一" / "metadata").resolve()
        else:
            self.metadata_dir = (root / "题库资料" / subject_folder_name / "metadata").resolve()

        if problems_dir and Path(problems_dir).exists():
            self.problems_dir = Path(problems_dir).resolve()
        elif (root / "题库资料" / subject_folder_name / "problems").exists():
            self.problems_dir = (root / "题库资料" / subject_folder_name / "problems").resolve()
        elif (root / "题库资料" / "880数学一" / "problems").exists():
            self.problems_dir = (root / "题库资料" / "880数学一" / "problems").resolve()
        else:
            self.problems_dir = (root / "题库资料" / subject_folder_name / "problems").resolve()

        self.questions_by_id: dict[str, QuestionItem] = {}
        self.chapters: list[str] = []
        self._is_loaded = False

    @staticmethod
    def normalize_id(raw_id: str) -> str:
        s = raw_id.strip().replace("—", "-").replace("–", "-").replace("_", "-")
        parts = [p.strip() for p in s.split("-") if p.strip()]
        # 新四段:章-篇-题型-序号(如 03-基础-选-03)
        if len(parts) == 4 and parts[0].isdigit() and parts[3].isdigit():
            return f"{int(parts[0]):02d}-{parts[1]}-{parts[2]}-{int(parts[3]):02d}"
        # 旧三段:章-篇-序号(兼容历史导入)
        if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit():
            return f"{int(parts[0]):02d}-{parts[1]}-{int(parts[2]):02d}"
        return s

    def load(self) -> list[QuestionItem]:
        if self._is_loaded and self.questions_by_id:
            return list(self.questions_by_id.values())

        raw_metadata = self._load_metadata()
        raw_problems = self._load_problems(raw_metadata)

        # 题面(markdown)与元数据(metadata)的切题编号在每章"基础/综合"分界处会差一格,
        # 直接按 ID 直配会让题面配上邻题的元数据(考点/解析)、并留下空题干。
        # 解析器是按文档顺序吐题块的,故按每章 (sec_rank, 题号) 排序后位置一一对齐即可归位。
        body_by_metaid = self._align_bodies_by_position(raw_metadata, raw_problems)

        combined: dict[str, QuestionItem] = {}
        all_ids = set(raw_metadata.keys())

        # 严格按照 (章节序号, 基础题1 -> 综合题2 -> 拓展题3, 题号) 排序
        for qid in sorted(all_ids, key=parse_qid_tuple):
            meta = raw_metadata[qid]
            body = body_by_metaid.get(qid, {})

            chapter_name = meta.get("chapter") or body.get("chapter") or "未分类章节"
            ch_num = parse_chapter_number(chapter_name, qid)
            category = classify_category(chapter_name, ch_num)

            # 解析难度(md 原文 body 优先:题型/难度标题干净,metadata 的 id 编号有噪声)
            sec_str = body.get("section") or meta.get("section") or "基础题"
            if "基础" in sec_str:
                diff = DifficultyLevel.BASIC
            elif "拓展" in sec_str or "拔高" in sec_str:
                diff = DifficultyLevel.ADVANCED
            else:
                diff = DifficultyLevel.COMPREHENSIVE

            # 解析题型(同上,以 md 原文为准)
            type_str = body.get("question_type") or meta.get("question_type") or "选择题"
            if "填空" in type_str:
                qtype = QuestionType.FILL_BLANK
            elif "解答" in type_str or "计算" in type_str or "证明" in type_str or "大题" in type_str:
                qtype = QuestionType.SOLUTION
            else:
                qtype = QuestionType.CHOICE

            q_item = QuestionItem(
                id=qid,
                chapter=chapter_name,
                category=category,
                difficulty=diff,
                question_type=qtype,
                core_knowledge=meta.get("core_knowledge") or [],
                dimension=meta.get("dimension") or "技巧计算",
                pitfall_analysis=meta.get("pitfall_analysis") or "",
                tags=meta.get("tags") or [],
                recommend_weight=int(meta.get("recommend_weight") or 3),
                stem=body.get("stem") or "",
                options=body.get("options") or [],
                answer=body.get("answer") or meta.get("answer") or "",
                solution=body.get("solution") or meta.get("solution") or "",
                source_file=body.get("source_file") or meta.get("source_file") or "",
                book=meta.get("book") or "880",
            )
            combined[qid] = q_item

        # 重编号:combined 已按 md 文档顺序排列(章内 选→填→解 单调)。
        # 按 (章, 篇, 题型) 三重计数器赋予新 ID 章-篇-题型-序号(如 03-基础-选-03),
        # 使题号与原书"每个题型各自从 1 编号"完全对应。题型/难度已取自 md 原文,
        # 故 metadata 的 id 编号噪声在此被自动修正。
        SEC_SHORT = {DifficultyLevel.BASIC: "基础", DifficultyLevel.COMPREHENSIVE: "综合", DifficultyLevel.ADVANCED: "拓展"}
        TYPE_SHORT = {QuestionType.CHOICE: "选", QuestionType.FILL_BLANK: "填", QuestionType.SOLUTION: "解"}
        renumbered: dict[str, QuestionItem] = {}
        counters: dict[tuple[int, str, str], int] = {}
        for q in combined.values():
            ch_num = parse_chapter_number(q.chapter, q.id)
            sec_short = SEC_SHORT.get(q.difficulty, "综合")
            type_short = TYPE_SHORT.get(q.question_type, "选")
            key = (ch_num, sec_short, type_short)
            counters[key] = counters.get(key, 0) + 1
            new_id = f"{ch_num:02d}-{sec_short}-{type_short}-{counters[key]:02d}"
            q.id = new_id
            renumbered[new_id] = q

        self.questions_by_id = renumbered
        self._is_loaded = True

        # 构建章节顺序
        ch_order: dict[str, int] = {}
        for q in self.questions_by_id.values():
            num = parse_chapter_number(q.chapter, q.id)
            ch_order[q.chapter] = min(ch_order.get(q.chapter, 999), num)
        self.chapters = sorted(ch_order.keys(), key=lambda c: (ch_order[c], c))

        logger.info(f"[{self.subject.value}] 成功加载 {len(self.questions_by_id)} 道题目，覆盖 {len(self.chapters)} 个章节。")
        return list(self.questions_by_id.values())

    def canonical_ids(self, book: str | None = None) -> list[str]:
        """按 canonical 顺序返回题号；给定 book 时仅返回该书题目（默认全部）。

        questions_by_id 已按 parse_qid_tuple 排序后插入且 dict 保序，
        故过滤后顺序与全量一致。用于 URL 位图的稳定 canonical 列表。
        """
        if book is None:
            return list(self.questions_by_id.keys())
        return [qid for qid, q in self.questions_by_id.items()
                if getattr(q, "book", "880") == book]

    @staticmethod
    def _align_bodies_by_position(
        raw_metadata: dict[str, dict[str, Any]],
        raw_problems: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """按每章文档顺序把题面(body)对齐到元数据 ID。

        解析器逐题块吐出 body 并按 section 顺序编号,元数据也按 section 顺序编号,
        二者在每章内都保持文档顺序,只是"基础/综合"分界处口径差一格。因此在每章内
        各自按 (sec_rank, 题号) 排序后按位置 zip,即可让第 i 道题面配到第 i 条元数据。

        某章两侧题数不相等时(理论上不应发生),该章退化为原来的按 ID 直配,避免误配。
        """
        def ch_of(qid: str) -> str:
            return qid.split("-")[0]

        meta_by_ch: dict[str, list[str]] = {}
        prob_by_ch: dict[str, list[str]] = {}
        for qid in raw_metadata:
            meta_by_ch.setdefault(ch_of(qid), []).append(qid)
        for cid in raw_problems:
            prob_by_ch.setdefault(ch_of(cid), []).append(cid)

        aligned: dict[str, dict[str, Any]] = {}
        for ch, mids in meta_by_ch.items():
            mids_sorted = sorted(mids, key=parse_qid_tuple)
            bids_sorted = sorted(prob_by_ch.get(ch, []), key=parse_qid_tuple)
            if len(mids_sorted) == len(bids_sorted):
                for mid, bid in zip(mids_sorted, bids_sorted):
                    aligned[mid] = raw_problems[bid]
            else:
                # 数量不等:保守退回按 ID 直配,避免整章错配
                for mid in mids_sorted:
                    if mid in raw_problems:
                        aligned[mid] = raw_problems[mid]
        return aligned

    def _load_metadata(self) -> dict[str, dict[str, Any]]:
        meta_dict: dict[str, dict[str, Any]] = {}
        if not self.metadata_dir.exists():
            return meta_dict

        json_files = sorted(self.metadata_dir.glob("*.json"))
        chapter_files = [f for f in json_files if "全章节" not in f.name]
        files_to_read = chapter_files if chapter_files else json_files

        for jf in files_to_read:
            try:
                data = json.loads(jf.read_text(encoding="utf-8-sig"))
                if not isinstance(data, list):
                    data = [data]
                for item in data:
                    qid = self.normalize_id(item.get("id") or item.get("question_id") or "")
                    if qid:
                        item["id"] = qid
                        item["source_file"] = jf.name
                        meta_dict[qid] = item
            except Exception as e:
                logger.warning(f"读取元数据文件 {jf.name} 失败: {e}")
        return meta_dict

    def _load_problems(self, metadata_lookup: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        problems_dict: dict[str, dict[str, Any]] = {}
        if not self.problems_dir.exists():
            return problems_dict

        md_files = sorted(self.problems_dir.glob("*.md"))
        for mf in md_files:
            try:
                content = mf.read_text(encoding="utf-8-sig")
                parsed = self._parse_markdown(content, mf.name, metadata_lookup)
                problems_dict.update(parsed)
            except Exception as e:
                logger.warning(f"解析题目文件 {mf.name} 失败: {e}")
        return problems_dict

    def _parse_markdown(self, text: str, filename: str, metadata_lookup: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        
        chapter_match = re.search(r"^[#= ]*([第\d一二三四五六七八九十]+章[^\n\r=]+)", text, re.M)
        chapter_name = chapter_match.group(1).strip() if chapter_match else filename.replace(".md", "").strip()
        ch_num = parse_chapter_number(chapter_name)

        current_section = "基础题"
        current_type = "选择题"
        
        lines = text.splitlines()
        q_blocks: list[tuple[str, str, int, list[str]]] = []
        
        cur_q_lines: list[str] = []
        cur_q_num = 0
        # 快照:题目所属篇/题型应在它"开始"那一刻锁定。若延迟到下一题才入库,
        # 中间可能已越过 ### 题型 或 ## 篇 标题,导致每个题型/篇的最后一题被误判
        # 为下一段(如基础选择的末题落到填空、综合解答末题落到拓展)。
        cur_q_sec = current_section
        cur_q_type = current_type

        for line in lines:
            trimmed = line.strip()
            if trimmed.startswith("## ") or ("【" in trimmed and "】" in trimmed):
                if "基础" in trimmed:
                    current_section = "基础题"
                elif "综合" in trimmed:
                    current_section = "综合题"
                elif "拓展" in trimmed or "拔高" in trimmed:
                    current_section = "拓展题"
                continue

            if trimmed.startswith("### ") or "选择题" in trimmed or "填空题" in trimmed or "解答题" in trimmed:
                if "选择" in trimmed:
                    current_type = "选择题"
                elif "填空" in trimmed:
                    current_type = "填空题"
                elif "解答" in trimmed or "计算" in trimmed or "证明" in trimmed:
                    current_type = "解答题"
                continue

            q_match = re.match(r"^(?:\*\*\((?P<n1>\d+)\)\*\*|(?P<n2>\d+)[.．、]|（(?P<n3>\d+)）)\s*(?P<rest>.*)$", trimmed)
            if q_match:
                if cur_q_num > 0 and cur_q_lines:
                    q_blocks.append((cur_q_sec, cur_q_type, cur_q_num, list(cur_q_lines)))
                    cur_q_lines.clear()

                n_str = q_match.group("n1") or q_match.group("n2") or q_match.group("n3")
                cur_q_num = int(n_str)
                rest = q_match.group("rest")
                cur_q_lines.append(rest)
                cur_q_sec, cur_q_type = current_section, current_type  # 锁定本题的篇/题型
            else:
                if cur_q_num > 0:
                    cur_q_lines.append(line)

        if cur_q_num > 0 and cur_q_lines:
            q_blocks.append((cur_q_sec, cur_q_type, cur_q_num, list(cur_q_lines)))

        # 按 section 递增赋予与元数据一致的 candidate_id
        sec_counters: dict[str, int] = {}
        for section, qtype, num, raw_lines in q_blocks:
            full_raw_text = "\n".join(raw_lines).strip()
            stem, options, answer, solution = self._extract_stem_and_options(full_raw_text)
            # 渲染防线:$ 不成对会让 KaTeX 把后续内容(含括号)整段吞掉。
            # 此时删光该字段的 $,退化为纯文本 —— 宁可不渲染,也不吞内容。
            stem = self._balance_dollars(stem)
            options = [self._balance_dollars(o) for o in options]
            # 渲染防线:行内 $...$ 内含真实换行时 remark-math 配不上对,整段退化为纯文本
            # (如多行矩阵)。数学模式里空白无意义、换行由 \\ 控制,故把行内公式内换行折成空格。
            stem = self._collapse_inline_math_newlines(stem)
            options = [self._collapse_inline_math_newlines(o) for o in options]
            # 把 ![](相对路径) 图片内联成 base64 data URI(网页与 PDF 都能显示,
            # 不依赖运行目录);源文件缺失时退化为占位文字,避免裂图。
            stem = self._embed_images(stem)
            # HTML <table> 转 Markdown 管道表格:raw HTML 表格内的 $...$ 不会被
            # KaTeX 渲染(显示成源码),而管道表格单元格是 markdown 文本,公式正常渲染。
            stem = self._html_table_to_markdown(stem)

            sec_short = "基础" if "基础" in section else ("拓展" if "拓展" in section else "综合")
            sec_counters[sec_short] = sec_counters.get(sec_short, 0) + 1
            seq_idx = sec_counters[sec_short]
            candidate_id = f"{ch_num:02d}-{sec_short}-{seq_idx:02d}"

            results[candidate_id] = {
                "id": candidate_id,
                "chapter": chapter_name,
                "section": section,
                "question_type": qtype,
                "stem": stem,
                "options": options,
                "answer": answer,
                "solution": solution,
                "source_file": filename,
            }

        return results

    @staticmethod
    def _balance_dollars(text: str) -> str:
        """$ 不成对时删光该字段的 $(排除 $$ 块)。防止 KaTeX 吞掉后续内容。"""
        if not text:
            return text
        if text.replace("$$", "").count("$") % 2 != 0:
            return text.replace("$", "")
        return text

    @staticmethod
    def _html_table_to_markdown(text: str) -> str:
        """把内联 <table>...</table> 转成 Markdown 管道表格。

        Streamlit/remark-math 与 Python-Markdown 都不会渲染 raw HTML 单元格里的
        $...$ 公式(显示成源码);管道表格的单元格是 markdown 文本,公式正常渲染。
        管道表格要求首尾有空行、每行独占一行。
        """
        if not text or "<table" not in text.lower():
            return text

        def cells(row_html: str) -> list[str]:
            parts = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S | re.I)
            # 单元格内可能自带首尾空格,去掉;管道符转义避免破坏表格
            return [c.strip().replace("|", r"\|") or " " for c in parts]

        def conv(m: re.Match) -> str:
            rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), flags=re.S | re.I)
            rows = [cells(r) for r in rows_html]
            rows = [r for r in rows if r]
            if not rows:
                return ""
            ncol = max(len(r) for r in rows)
            rows = [r + [" "] * (ncol - len(r)) for r in rows]
            # 首行作表头,其后插入分隔行
            head = "| " + " | ".join(rows[0]) + " |"
            sep = "| " + " | ".join(["---"] * ncol) + " |"
            body = ["| " + " | ".join(r) + " |" for r in rows[1:]]
            return "\n\n" + "\n".join([head, sep, *body]) + "\n\n"

        return re.sub(r"<table[^>]*>(.*?)</table>", conv, text, flags=re.S | re.I)

    def _embed_images(self, text: str) -> str:
        """把题干里的 ![alt](path) 图片引用内联成 base64 <img> 标签。

        path 相对 problems 目录解析。文件存在 → data URI 内联(网页 st.markdown
        与 PDF 无头浏览器都能显示,不受运行目录影响);文件缺失 → 退化为占位文字,
        不再显示裂图。
        """
        if not text or "![" not in text:
            return text

        def repl(m: re.Match) -> str:
            alt = m.group(1)
            ref = m.group(2).strip()
            # 只处理本地相对路径,http(s)/已是 data URI 的原样保留
            if ref.startswith(("http://", "https://", "data:")):
                return m.group(0)
            img_path = (self.problems_dir / ref.lstrip("./")).resolve()
            if not img_path.exists():
                label = alt.strip() or "图"
                return f"*({label}见原书)*"
            mime = mimetypes.guess_type(str(img_path))[0] or "image/jpeg"
            try:
                b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
            except OSError:
                return f"*({alt.strip() or '图'}见原书)*"
            return (f'<img src="data:{mime};base64,{b64}" alt="{alt}" '
                    f'style="max-width:100%;height:auto;display:block;margin:8px auto;" />')

        return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, text)

    @staticmethod
    def _collapse_inline_math_newlines(text: str) -> str:
        """把行内 $...$ 公式内的真实换行折成空格。

        Streamlit/remark-math 的行内公式不允许跨行,一旦 $...$ 内出现换行(如多行
        矩阵),定界符配不上对,整段退化为纯文本。数学模式里空白无意义、换行由 \\
        控制,故折成空格语义不变。$$...$$ 显示块能正常处理换行,原样保留。
        """
        if not text or "$" not in text:
            return text
        out: list[str] = []
        i, n = 0, len(text)
        while i < n:
            if text[i] == "$":
                if i + 1 < n and text[i + 1] == "$":  # 显示块 $$...$$,原样拷贝
                    j = text.find("$$", i + 2)
                    if j == -1:
                        out.append(text[i:]); break
                    out.append(text[i:j + 2]); i = j + 2; continue
                j = text.find("$", i + 1)  # 行内 $...$
                if j == -1:
                    out.append(text[i:]); break
                out.append("$" + text[i + 1:j].replace("\n", " ") + "$")
                i = j + 1; continue
            out.append(text[i]); i += 1
        return "".join(out)

    @staticmethod
    def _extract_stem_and_options(raw_text: str) -> tuple[str, list[str], str, str]:
        lines = raw_text.splitlines()
        stem_lines: list[str] = []
        options: list[str] = []
        answer = ""
        solution_lines: list[str] = []

        is_solution = False
        opt_pattern = re.compile(r"^([A-D][.．、\s]\s*.+)$")

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue

            if "【解析】" in trimmed or "### 解析" in trimmed or "### 答案" in trimmed or "【答案】" in trimmed:
                is_solution = True
                ans_match = re.search(r"(?:答案|参考答案)[：:\s]*([A-D\d\w\-+\\$/]+)", trimmed)
                if ans_match:
                    answer = ans_match.group(1).strip()
                continue

            if is_solution:
                solution_lines.append(trimmed)
                continue

            m_opt = opt_pattern.match(trimmed)
            if m_opt:
                options.append(trimmed)
            elif re.match(r"^A[.\s].+B[.\s].+", trimmed):
                split_opts = re.findall(r"([A-D][.．、\s][^A-D]+)", trimmed)
                options.extend([o.strip() for o in split_opts if o.strip()])
            else:
                stem_lines.append(line)

        stem = "\n".join(stem_lines).strip()
        solution = "\n".join(solution_lines).strip()
        return stem, options, answer, solution

    def get_questions_for_subject(self, subject: SubjectType) -> list[QuestionItem]:
        """按科目获取题库"""
        if subject == self.subject:
            return self.load()
        # 实例化对应科目的 loader 加载对应专属题库
        sub_loader = BankLoader(subject=subject)
        return sub_loader.load()
