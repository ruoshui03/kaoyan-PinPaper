"""
考研数学《880》智能拼好卷 & 错题标练系统 - 高性能 Web API 服务端
连接 Clean-Room core 算法引擎与纯原生现代 Web 前端，全面支持数学一、数学二、数学三独立题库
"""
from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

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
from core import contribution as contribution_hub
from core.chapter_dist import load_chapter_dist, scale_dist

# Initialize Core Services
ROOT_DIR = Path(__file__).parent.resolve()
WEB_DIR = ROOT_DIR / "web"
WEB_DIR.mkdir(exist_ok=True)

# Preload loaders for all 3 subjects
loaders: dict[SubjectType, BankLoader] = {
    SubjectType.MATH_1: BankLoader(subject=SubjectType.MATH_1),
    SubjectType.MATH_2: BankLoader(subject=SubjectType.MATH_2),
    SubjectType.MATH_3: BankLoader(subject=SubjectType.MATH_3),
}
for l in loaders.values():
    l.load()

state_mgr = StateManager()
pdf_service = PDFService()
ai_tutor = AITutor()

# ThreadingHTTPServer 是多线程的，而 StateManager 直接读写同一个 JSON 文件。
# 并发错题标记会互相覆盖（后写胜出，前一次标记凭空消失），故所有状态写入加锁。
STATE_LOCK = threading.RLock()


def reload_banks() -> dict[str, int]:
    """重新加载全部题库（答案包 / 新书目变更後调用，无需重启服务）。"""
    counts: dict[str, int] = {}
    with STATE_LOCK:
        for sub, l in loaders.items():
            l.questions_by_id = {}
            l.chapters = []
            l._is_loaded = False
            counts[sub.value] = len(l.load())
    load_chapter_dist.cache_clear()
    return counts


def _norm_answer(s: str) -> str:
    """答案归一化后比较：去空白与常见标点，大写；纯字母多选（如 AC / CA）排序后比较。"""
    t = re.sub(r"[\s，,、（）()\[\]{}<>。.;；:：'\"`]", "", str(s or "")).upper()
    if t and all(c in "ABCDEFG" for c in t):
        return "".join(sorted(t))
    return t


def parse_subject(subject_str: str) -> SubjectType:
    if "二" in subject_str or subject_str == "数学二":
        return SubjectType.MATH_2
    elif "三" in subject_str or subject_str == "数学三":
        return SubjectType.MATH_3
    else:
        return SubjectType.MATH_1


class AppAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_file(self, file_path: Path, content_type: str | None = None) -> bool:
        """按路径发送静态文件（供 /assets/* 之类仓库内资源使用）。"""
        try:
            if not file_path.exists() or not file_path.is_file():
                return False
            body = file_path.read_bytes()
        except OSError:
            return False
        ctype = content_type or (mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 仓库内静态资源（如本地 KaTeX）：/assets/katex/katex.min.css
        if path.startswith("/assets/"):
            rel = path[len("/assets/"):].lstrip("/")
            if ".." not in rel and self._send_file(ROOT_DIR / "assets" / rel):
                return
            self._send_json({"status": "error", "message": "asset not found"}, 404)
            return

        # 本地答案库目录浏览（只读，便于手工取用 contributions）
        if path.startswith("/solutions/"):
            rel = path[len("/solutions/"):].lstrip("/")
            if ".." not in rel and rel and self._send_file(ROOT_DIR / "solutions" / rel):
                return
            self._send_json({"status": "error", "message": "file not found"}, 404)
            return

        # API: 答案/解析共享中心状态
        if path == "/api/solutions/status":
            self._send_json({
                "status": "ok",
                "consent": contribution_hub.read_consent(ROOT_DIR),
                "stats": contribution_hub.stats(ROOT_DIR),
            })
            return

        # API: 生成待填答案模板
        if path == "/api/solutions/template":
            sub_str = query.get("subject", ["数学一"])[0]
            book = query.get("book", ["880"])[0]
            limit = int(query.get("limit", ["200"])[0] or 200)
            cur_sub = parse_subject(sub_str)
            try:
                text = contribution_hub.gen_template(
                    book, cur_sub, loaders[cur_sub].load(), limit=limit)
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 500)
                return
            self._send_json({"status": "ok", "book": book, "subject": cur_sub.value,
                             "markdown": text})
            return

        # API: Get System Status & Chapters
        if path == "/api/init":
            sub_str = query.get("subject", ["数学一"])[0]
            cur_sub = parse_subject(sub_str)
            cur_loader = loaders[cur_sub]
            cur_questions = cur_loader.load()

            chapters_data = []
            for ch in cur_loader.chapters:
                qs = [q for q in cur_questions if q.chapter == ch]
                cat = qs[0].category.value if qs else "未知"
                chapters_data.append({
                    "name": ch,
                    "category": cat,
                    "count": len(qs),
                    "isCovered": ch in state_mgr.historical_covered_chapters,
                    "wrongCount": sum(1 for q in qs if state_mgr.is_wrong_marked(q.id)),
                })
            
            # 书籍清单与答案覆盖率：前端据此动态显示，不再写死题数
            books_meta = []
            for book_name in sorted({q.book for q in cur_questions}):
                items = [q for q in cur_questions if q.book == book_name]
                books_meta.append({
                    "name": book_name,
                    "count": len(items),
                    "answerCoverage": round(
                        sum(1 for q in items if q.answer.strip()) / max(1, len(items)) * 100, 1),
                })
            self._send_json({
                "status": "ok",
                "currentSubject": cur_sub.value,
                "totalQuestions": len(cur_questions),
                "totalChapters": len(cur_loader.chapters),
                "wrongTotal": len(state_mgr.wrong_questions),
                "coveredChapters": list(state_mgr.historical_covered_chapters),
                "chapters": chapters_data,
                "books": books_meta,
                "answerCoverage": round(
                    sum(1 for q in cur_questions if q.answer.strip()) / max(1, len(cur_questions)) * 100, 1),
                "math1": MATH_1_CHAPTERS,
                "math2": MATH_2_CHAPTERS,
                "math3": MATH_3_CHAPTERS,
            })
            return

        # API: Query Questions in Chapter
        if path == "/api/questions":
            sub_str = query.get("subject", ["数学一"])[0]
            cur_sub = parse_subject(sub_str)
            cur_loader = loaders[cur_sub]
            cur_questions = cur_loader.load()

            ch = query.get("chapter", [""])[0]
            diff = query.get("difficulty", ["全部"])[0]
            qtype = query.get("type", ["全部"])[0]
            kw = query.get("keyword", [""])[0].strip()

            matched = cur_questions
            if ch:
                matched = [q for q in matched if q.chapter == ch]
            if diff != "全部":
                matched = [q for q in matched if diff in q.difficulty.value]
            if qtype != "全部":
                matched = [q for q in matched if qtype in q.question_type.value]
            if kw:
                matched = [q for q in matched if kw in q.stem or kw in q.id or any(kw in t for t in q.tags)]

            res = []
            for q in matched:
                res.append({
                    "id": q.id,
                    "chapter": q.chapter,
                    "category": q.category.value,
                    "difficulty": q.difficulty.value,
                    "type": q.question_type.value,
                    "stem": q.stem,
                    "options": q.options,
                    "answer": q.answer,
                    "solution": q.solution,
                    "coreKnowledge": q.core_knowledge,
                    "pitfallAnalysis": q.pitfall_analysis,
                    "tags": q.tags,
                    "isWrong": state_mgr.is_wrong_marked(q.id),
                })
            self._send_json({"count": len(res), "questions": res})
            return

        # API: Get Wrong Questions Pool
        if path == "/api/wrong-pool":
            sub_str = query.get("subject", ["数学一"])[0]
            cur_sub = parse_subject(sub_str)
            cur_loader = loaders[cur_sub]
            cur_questions = cur_loader.load()

            w_ids = state_mgr.get_wrong_question_ids()
            matched = [q for q in cur_questions if q.id in w_ids]
            res = []
            for q in matched:
                rec = state_mgr.wrong_questions.get(q.id)
                res.append({
                    "id": q.id,
                    "chapter": q.chapter,
                    "difficulty": q.difficulty.value,
                    "type": q.question_type.value,
                    "stem": q.stem,
                    "options": q.options,
                    "answer": q.answer,
                    "solution": q.solution,
                    "coreKnowledge": q.core_knowledge,
                    "pitfallAnalysis": q.pitfall_analysis,
                    "tags": q.tags,
                    "errorTag": rec.error_tag if rec else "概念模糊",
                    "note": rec.user_note if rec else "",
                })
            self._send_json({"count": len(res), "questions": res})
            return

        # Static Assets
        return super().do_GET()

    def do_POST(self):
        """统一异常处理：任何未捕获异常都回 JSON 500，而不是把 traceback 丢给客户端。"""
        try:
            self._handle_post()
        except Exception as e:  # noqa: BLE001 - 兜底成 JSON，避免前端拿到 HTML 错误页
            try:
                self._send_json({"status": "error", "message": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass

    def _handle_post(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        req_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(req_body) if req_body else {}
        except json.JSONDecodeError:
            self._send_json({"status": "error", "message": "请求体不是合法 JSON"}, 400)
            return

        # API: Toggle Wrong Mark
        if path == "/api/wrong/toggle":
            qid = payload.get("id", "")
            error_tag = payload.get("errorTag", "概念模糊")
            note = payload.get("note", "")
            if qid:
                with STATE_LOCK:
                    is_marked = state_mgr.toggle_wrong_question(qid, error_tag=error_tag, note=note)
                self._send_json({"status": "ok", "id": qid, "isMarked": is_marked, "wrongTotal": len(state_mgr.wrong_questions)})
            else:
                self._send_json({"status": "error", "message": "Missing ID"}, 400)
            return

        # API: Batch Mark Wrong
        if path == "/api/wrong/batch-mark":
            qids = payload.get("ids", [])
            chapter = payload.get("chapter", "")
            num_str = payload.get("numbers", "")
            sub_str = payload.get("subject", "数学一")
            cur_sub = parse_subject(sub_str)
            cur_questions = loaders[cur_sub].load()
            
            if num_str and chapter:
                nums = re.findall(r"\d+", num_str)
                ch_qs = [q for q in cur_questions if q.chapter == chapter]
                for n in nums:
                    val = int(n)
                    matched = [q for q in ch_qs if f"-{val:02d}" in q.id or f"_{val}" in q.id]
                    if matched and matched[0].id not in qids:
                        qids.append(matched[0].id)

            count = state_mgr.batch_mark_wrong(qids)
            self._send_json({"status": "ok", "markedCount": count, "wrongTotal": len(state_mgr.wrong_questions)})
            return

        # API: Batch Unmark
        if path == "/api/wrong/batch-unmark":
            qids = payload.get("ids", [])
            chapter = payload.get("chapter", "")
            num_str = payload.get("numbers", "")
            sub_str = payload.get("subject", "数学一")
            cur_sub = parse_subject(sub_str)
            cur_questions = loaders[cur_sub].load()
            
            if num_str and chapter:
                nums = re.findall(r"\d+", num_str)
                ch_qs = [q for q in cur_questions if q.chapter == chapter]
                for n in nums:
                    val = int(n)
                    matched = [q for q in ch_qs if f"-{val:02d}" in q.id or f"_{val}" in q.id]
                    if matched and matched[0].id not in qids:
                        qids.append(matched[0].id)

            count = state_mgr.batch_unmark_wrong(qids)
            self._send_json({"status": "ok", "unmarkedCount": count, "wrongTotal": len(state_mgr.wrong_questions)})
            return

        # API: Reset Coverage Cycle
        if path == "/api/coverage/reset":
            state_mgr.reset_coverage_cycle()
            self._send_json({"status": "ok", "coveredChapters": []})
            return

        # API: Generate Paper
        if path == "/api/generate-paper":
            mode_str = payload.get("mode", "10-6-6")
            subject_str = payload.get("subject", "数学一")
            cur_sub = parse_subject(subject_str)
            cur_loader = loaders[cur_sub]
            cur_questions = cur_loader.load()

            tag_filter = payload.get("tag", "全部")
            diff_weights_dict = payload.get("diffWeights", {"基础": 1.0, "综合": 1.2, "拓展": 0.8})
            
            default_chapters = (
                MATH_2_CHAPTERS if cur_sub == SubjectType.MATH_2
                else (MATH_3_CHAPTERS if cur_sub == SubjectType.MATH_3 else MATH_1_CHAPTERS)
            )
            target_chapters = payload.get("chapters") or default_chapters
            only_wrong = payload.get("onlyWrong", False)

            if mode_str == "5-3-3":
                mode = PaperMode.SPRINT_5_3_3
            elif mode_str == "3-bundle":
                mode = PaperMode.BUNDLE_3_PAPERS
            elif mode_str == "custom":
                mode = PaperMode.CUSTOM
            else:
                mode = PaperMode.FULL_10_6_6

            diff_weights = {
                DifficultyLevel.BASIC: float(diff_weights_dict.get("基础", 1.0)),
                DifficultyLevel.COMPREHENSIVE: float(diff_weights_dict.get("综合", 1.2)),
                DifficultyLevel.ADVANCED: float(diff_weights_dict.get("拓展", 0.8)),
            }

            candidate_pool = cur_questions
            if only_wrong:
                w_ids = state_mgr.get_wrong_question_ids()
                candidate_pool = [q for q in cur_questions if q.id in w_ids]
                if not candidate_pool:
                    candidate_pool = cur_questions

            # 错题优先池 / 占比 / 轮换 / 次数加权：此前 Web 端完全没有接，
            # 错题占比拉满也几乎抽不到错题。此处与 Streamlit 端语义对齐。
            priority_ratio = float(payload.get("wrongRatio", 0.0) or 0.0)
            wrong_ids = state_mgr.get_active_wrong_pool() or state_mgr.get_wrong_question_ids()
            enabled_categories = None
            cats = payload.get("categories")
            if cats:
                mapping = {c.value: c for c in ChapterCategory}
                picked = {mapping[c] for c in cats if c in mapping}
                if picked:
                    enabled_categories = picked

            # 真题章节分布软权重：0=不启用，1=完全按真题热点
            dist_strength = float(payload.get("chapterDistStrength", 0.0) or 0.0)
            chapter_weights = scale_dist(load_chapter_dist(cur_sub.value, str(ROOT_DIR)), dist_strength)

            engine = PaperEngine(candidate_pool)
            req = EngineRequest(
                title=f"考研数学{cur_sub.value}智能拼好卷",
                subject=cur_sub,
                mode=mode,
                target_chapters=set(target_chapters),
                difficulty_weights=diff_weights,
                tag_filter=tag_filter,
                seed=random.randint(1000, 99999),
                historical_covered_chapters=state_mgr.historical_covered_chapters,
                historical_seen_question_ids=state_mgr.historical_seen_ids,
                candidate_question_pool=candidate_pool,
                enabled_categories=enabled_categories,
                priority_pool_ids=set(wrong_ids),
                priority_ratio=priority_ratio,
                exclude_seen=bool(payload.get("excludeSeen", True)),
                priority_practiced_ids=set(state_mgr.wrong_rotation_ids),
                priority_wrong_counts=state_mgr.get_wrong_counts(set(wrong_ids)),
                chapter_weights=chapter_weights,
            )

            if mode == PaperMode.BUNDLE_3_PAPERS:
                bundle = engine.generate_bundle(req, bundle_size=3)
                papers_res = []
                for p in bundle.papers:
                    with STATE_LOCK:
                        state_mgr.record_paper_generation(p.questions)
                    papers_res.append(self._serialize_paper(p))
                self._send_json({
                    "status": "ok",
                    "isBundle": True,
                    "bundleTitle": bundle.title,
                    "allCoveredChapters": list(bundle.all_covered_chapters),
                    "coverageRatio": bundle.total_coverage_ratio,
                    "papers": papers_res,
                })
            else:
                paper = engine.generate_single_paper(req)
                with STATE_LOCK:
                    state_mgr.record_paper_generation(paper.questions)
                self._send_json({
                    "status": "ok",
                    "isBundle": False,
                    "paper": self._serialize_paper(paper),
                })
            return

        # API: Archive to 试卷库/
        if path == "/api/archive-paper":
            paper_data = payload.get("paper", {})
            paper_id = paper_data.get("id", f"PAPER-{random.randint(1000,9999)}")
            questions_raw = paper_data.get("questions", [])
            sub_str = paper_data.get("subject", "数学一")
            cur_sub = parse_subject(sub_str)
            cur_loader = loaders[cur_sub]
            
            # Reconstruct PaperItem
            q_objs = [cur_loader.questions_by_id.get(q["id"]) for q in questions_raw if q["id"] in cur_loader.questions_by_id]
            reconstructed_paper = PaperItem(
                title=paper_data.get("title", f"考研数学880{cur_sub.value}智能拼好卷"),
                paper_id=paper_id,
                subject=cur_sub,
                mode=PaperMode.FULL_10_6_6,
                questions=[q for q in q_objs if q],
            )
            # 修正：generate_html 的签名是 edition=PDFEdition，旧调用写的是
            # is_solution_edition=... → 任何归档请求都会 TypeError 500。
            edition_raw = str(paper_data.get("edition", "") or "")
            if "解析" in edition_raw or "solution" in edition_raw or paper_data.get("withSolution"):
                edition = PDFEdition.SOLUTION
            elif "做题本" in edition_raw or "workbook" in edition_raw:
                edition = PDFEdition.WORKBOOK
            else:
                edition = PDFEdition.REAL_EXAM
            clean_html = pdf_service.generate_html(reconstructed_paper, edition=PDFEdition.REAL_EXAM)
            solved_html = pdf_service.generate_html(reconstructed_paper, edition=PDFEdition.SOLUTION)
            _ = edition  # 保留请求里的版式偏好，默认仍产真题版 + 解析版两份
            
            papers_dir = ROOT_DIR / "试卷库"
            papers_dir.mkdir(exist_ok=True)
            (papers_dir / f"{paper_id}_全真模考.html").write_text(clean_html, encoding="utf-8")
            (papers_dir / f"{paper_id}_详细解析.html").write_text(solved_html, encoding="utf-8")
            
            self._send_json({"status": "ok", "path": f"试卷库/{paper_id}_全真模考.html"})
            return

        # API: 热重载题库（导入答案包 / 新增题库后调用，无需重启服务）
        if path == "/api/reload":
            counts = reload_banks()
            self._send_json({"status": "ok", "counts": counts,
                             "answerCoverage": round(
                                 sum(1 for l in loaders.values() for q in l.questions_by_id.values()
                                     if q.answer.strip()) /
                                 max(1, sum(len(l.questions_by_id) for l in loaders.values())) * 100, 2)})
            return

        # API: 交卷判分（考场模式）
        if path == "/api/submit-answers":
            sub_str = payload.get("subject", "数学一")
            cur_sub = parse_subject(sub_str)
            answers = payload.get("answers", {}) or {}
            loader = loaders[cur_sub]
            loader.load()

            results: list[dict] = []
            wrong_ids: list[str] = []
            correct_ids: list[str] = []
            graded = 0
            correct = 0
            for qid, user_answer in answers.items():
                q = loader.questions_by_id.get(str(qid))
                std = ""
                solution = ""
                if q is not None:
                    std = (q.answer or "").strip()
                    solution = q.solution or ""
                ua = "" if user_answer is None else str(user_answer).strip()
                if not std:
                    status = "ungraded"          # 题库暂无标准答案，不判对错
                elif not ua:
                    status = "blank"             # 未作答，按错处理但不计分噪声
                    graded += 1
                    wrong_ids.append(str(qid))
                else:
                    graded += 1
                    if _norm_answer(std) == _norm_answer(ua):
                        status = "correct"
                        correct += 1
                        correct_ids.append(str(qid))
                    else:
                        status = "wrong"
                        wrong_ids.append(str(qid))
                results.append({
                    "id": str(qid),
                    "userAnswer": ua,
                    "standardAnswer": std,
                    "solution": solution,
                    "status": status,
                })

            # 错题反哺：答错/未答的题自动进错题本（走既有账本，与手动标错等价）
            marked = 0
            mastered = 0
            with STATE_LOCK:
                if wrong_ids:
                    marked = state_mgr.batch_mark_wrong(wrong_ids)
                # 错题闭环：重练答对的题自动移出活跃待练池，不再反复出现在错题优先卷里
                if correct_ids:
                    mastered = state_mgr.batch_mark_solved_correctly(correct_ids)
                # 本轮重练登记进轮换乘本（只登记本来就在错题本里的题号）
                if wrong_ids or correct_ids:
                    state_mgr.record_wrong_practice(list(wrong_ids) + list(correct_ids))

            self._send_json({
                "status": "ok",
                "total": len(results),
                "graded": graded,
                "correct": correct,
                "score": round(correct * 100.0 / graded, 1) if graded else 0.0,
                "ungraded": sum(1 for r in results if r["status"] == "ungraded"),
                "markedWrong": marked,
                "masteredCount": mastered,
                "results": results,
            })
            return

        # API: 设置共享授权（决定是否允许导出/推送贡献包）
        if path == "/api/solutions/consent":
            consent = contribution_hub.write_consent(
                share=bool(payload.get("share", False)),
                author=str(payload.get("author", "") or ""),
                attribution=bool(payload.get("attribution", True)),
                root=ROOT_DIR,
            )
            self._send_json({"status": "ok", "consent": contribution_hub.read_consent(ROOT_DIR),
                             "path": str(consent)})
            return

        # API: 导入贡献包（文件由前端上传为文本，或给出 URL / CID）
        if path == "/api/solutions/import":
            src = payload.get("source", "")
            book = payload.get("book") or None
            sub_str = payload.get("subject")
            if not src:
                self._send_json({"status": "error", "message": "缺少 source"}, 400)
                return
            cur_sub = parse_subject(sub_str) if sub_str else None
            known = None
            if cur_sub is not None:
                known = {q.id for q in loaders[cur_sub].load()
                         if (not book or getattr(q, "book", "") == book)}
            try:
                res = contribution_hub.import_pack(
                    src, valid_ids=known, root=ROOT_DIR,
                    strategy=str(payload.get("strategy", "remote")),
                    book_override=book,
                    subject_override=cur_sub.value if cur_sub else None,
                    secret=payload.get("secret"),
                )
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, 400)
                return
            # 答案已落盘 → 立刻热重载，否则本次进程内判分还是拿不到新答案
            if res.get("accepted"):
                res["reloaded"] = reload_banks()
            res["status"] = "ok"
            self._send_json(res)
            return

        # API: 导出贡献包（需已开启共享授权）
        if path == "/api/solutions/export":
            consent = contribution_hub.read_consent(ROOT_DIR)
            if not consent.get("share") and not payload.get("force"):
                self._send_json({"status": "error",
                                 "message": "未开启共享授权，导出已阻止（可在界面勾选后重试）"}, 403)
                return
            book = payload.get("book", "880")
            sub_str = payload.get("subject", "数学一")
            try:
                out = contribution_hub.export_pack(
                    book, parse_subject(sub_str), root=ROOT_DIR,
                    author=str(payload.get("author") or consent.get("author") or ""),
                    share=True, secret=payload.get("secret"),
                )
            except ValueError as e:
                self._send_json({"status": "error", "message": str(e)}, 400)
                return
            self._send_json({"status": "ok", "path": str(out),
                             "downloadUrl": f"/solutions/_outbox/{Path(out).name}"})
            return

        # API: AI Tutor Solve
        if path == "/api/ai-solve":
            qid = payload.get("id", "")
            sub_str = payload.get("subject", "数学一")
            cur_sub = parse_subject(sub_str)
            cur_loader = loaders[cur_sub]
            q_item = cur_loader.questions_by_id.get(qid)
            if not q_item:
                # Search across all loaders
                for l in loaders.values():
                    if qid in l.questions_by_id:
                        q_item = l.questions_by_id[qid]
                        break
            if not q_item:
                self._send_json({"status": "error", "message": "Question not found"}, 404)
                return
            ai_solution = "".join(list(ai_tutor.solve_question_stream(q_item)))
            self._send_json({"status": "ok", "solution": ai_solution})
            return

        self._send_json({"status": "error", "message": "Unknown endpoint"}, 404)

    def _serialize_paper(self, paper: PaperItem) -> dict:
        def _to_q_dict(q: QuestionItem):
            return {
                "id": q.id,
                "chapter": q.chapter,
                "category": q.category.value,
                "difficulty": q.difficulty.value,
                "type": q.question_type.value,
                "stem": q.stem,
                "options": q.options,
                "answer": q.answer,
                "solution": q.solution,
                "coreKnowledge": q.core_knowledge,
                "pitfallAnalysis": q.pitfall_analysis,
                "tags": q.tags,
                "book": getattr(q, "book", "") or "",   # 来自哪本题库，便于按书回填/统计
                "isWrong": state_mgr.is_wrong_marked(q.id),
            }

        return {
            "id": paper.paper_id,
            "title": paper.title,
            "subject": paper.subject.value,
            "mode": paper.mode.value,
            "totalCount": paper.total_count,
            "choiceQuestions": [_to_q_dict(q) for q in paper.choice_questions],
            "fillQuestions": [_to_q_dict(q) for q in paper.fill_questions],
            "solutionQuestions": [_to_q_dict(q) for q in paper.solution_questions],
            "allQuestions": [_to_q_dict(q) for q in paper.questions],
            "coveredChapters": list(paper.covered_chapters),
        }


def run_server(port: int = 8080):
    server = ThreadingHTTPServer(("0.0.0.0", port), AppAPIHandler)
    print(f"🚀 880 智能拼卷全新 Web 服务已启动: http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server(8080)
