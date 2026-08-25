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
from core.pdf_service import PDFService
from core.ai_tutor import AITutor
from core.state_manager import StateManager

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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

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
            
            self._send_json({
                "status": "ok",
                "currentSubject": cur_sub.value,
                "totalQuestions": len(cur_questions),
                "totalChapters": len(cur_loader.chapters),
                "wrongTotal": len(state_mgr.wrong_questions),
                "coveredChapters": list(state_mgr.historical_covered_chapters),
                "chapters": chapters_data,
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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        req_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        payload = json.loads(req_body) if req_body else {}

        # API: Toggle Wrong Mark
        if path == "/api/wrong/toggle":
            qid = payload.get("id", "")
            error_tag = payload.get("errorTag", "概念模糊")
            note = payload.get("note", "")
            if qid:
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

            engine = PaperEngine(candidate_pool)
            req = EngineRequest(
                title=f"考研数学《880》{cur_sub.value}智能拼好卷",
                subject=cur_sub,
                mode=mode,
                target_chapters=set(target_chapters),
                difficulty_weights=diff_weights,
                tag_filter=tag_filter,
                seed=random.randint(1000, 99999),
                historical_covered_chapters=state_mgr.historical_covered_chapters,
                historical_seen_question_ids=state_mgr.historical_seen_ids,
                candidate_question_pool=candidate_pool,
            )

            if mode == PaperMode.BUNDLE_3_PAPERS:
                bundle = engine.generate_bundle(req, bundle_size=3)
                papers_res = []
                for p in bundle.papers:
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
            clean_html = pdf_service.generate_html(reconstructed_paper, is_solution_edition=False)
            solved_html = pdf_service.generate_html(reconstructed_paper, is_solution_edition=True)
            
            papers_dir = ROOT_DIR / "试卷库"
            papers_dir.mkdir(exist_ok=True)
            (papers_dir / f"{paper_id}_全真模考.html").write_text(clean_html, encoding="utf-8")
            (papers_dir / f"{paper_id}_详细解析.html").write_text(solved_html, encoding="utf-8")
            
            self._send_json({"status": "ok", "path": f"试卷库/{paper_id}_全真模考.html"})
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
