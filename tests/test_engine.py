"""
考研数学智能组卷系统 - 核心功能与真题大纲槽位约束单元测试套件
"""
from __future__ import annotations

from pathlib import Path
import pytest

from core.bank_loader import BankLoader
from core.models import (
    ChapterCategory,
    DifficultyLevel,
    PaperMode,
    QuestionItem,
    QuestionType,
    SubjectType,
    MATH_1_CHAPTERS,
    MATH_2_CHAPTERS,
    MATH_3_CHAPTERS,
)
from core.paper_engine import EngineRequest, PaperEngine
from core.state_manager import StateManager


@pytest.fixture
def math1_questions() -> list[QuestionItem]:
    loader = BankLoader(subject=SubjectType.MATH_1)
    return loader.load()


@pytest.fixture
def math2_questions() -> list[QuestionItem]:
    loader = BankLoader(subject=SubjectType.MATH_2)
    return loader.load()


@pytest.fixture
def math3_questions() -> list[QuestionItem]:
    loader = BankLoader(subject=SubjectType.MATH_3)
    return loader.load()


def test_bank_loader_math1_structure(math1_questions):
    assert len(math1_questions) == 1121
    chapters = {q.chapter for q in math1_questions}
    assert len(chapters) == 23


def test_bank_loader_math2_structure(math2_questions):
    assert len(math2_questions) >= 900
    chapters = {q.chapter for q in math2_questions}
    assert len(chapters) == 12
    assert "第八章 无穷级数" not in chapters
    assert "第九章 曲线积分与曲面积分" not in chapters
    assert "第十五章 随机事件及其概率" not in chapters


def test_bank_loader_math3_structure(math3_questions):
    assert len(math3_questions) >= 1000
    chapters = {q.chapter for q in math3_questions}
    assert len(chapters) == 21
    assert any("经济" in ch for ch in chapters)
    assert "第四章 空间解析几何" not in chapters
    assert "第九章 曲线积分与曲面积分" not in chapters


def test_math1_standard_exam_slot_restrictions(math1_questions):
    """验证数学一真题标准槽位：1-4高数 5-7线代 8-10概率 11-14高数 15线代 16概率 17-20高数 21线代 22概率"""
    engine = PaperEngine(math1_questions)
    req = EngineRequest(
        title="2026 考研数学一真题标准模考",
        subject=SubjectType.MATH_1,
        mode=PaperMode.FULL_10_6_6,
        target_chapters=set(MATH_1_CHAPTERS),
        seed=2026,
    )
    paper = engine.generate_single_paper(req)
    assert len(paper.questions) == 22

    qs = paper.questions
    # 选择题 (1~10)
    for i in range(0, 4):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.ADVANCED_MATH, f"题号 {i+1} 应为高数，实际为 {qs[i].category}"
    for i in range(4, 7):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.LINEAR_ALGEBRA, f"题号 {i+1} 应为线代，实际为 {qs[i].category}"
    for i in range(7, 10):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.PROBABILITY, f"题号 {i+1} 应为概率，实际为 {qs[i].category}"

    # 填空题 (11~16)
    for i in range(10, 14):
        assert qs[i].question_type == QuestionType.FILL_BLANK
        assert qs[i].category == ChapterCategory.ADVANCED_MATH, f"题号 {i+1} 应为高数，实际为 {qs[i].category}"
    assert qs[14].question_type == QuestionType.FILL_BLANK
    assert qs[14].category == ChapterCategory.LINEAR_ALGEBRA, "第 15 题应为线代填空"
    assert qs[15].question_type == QuestionType.FILL_BLANK
    assert qs[15].category == ChapterCategory.PROBABILITY, "第 16 题应为概率填空"

    # 解答题 (17~22)
    for i in range(16, 20):
        assert qs[i].question_type == QuestionType.SOLUTION
        assert qs[i].category == ChapterCategory.ADVANCED_MATH, f"题号 {i+1} 应为高数，实际为 {qs[i].category}"
    assert qs[20].question_type == QuestionType.SOLUTION
    assert qs[20].category == ChapterCategory.LINEAR_ALGEBRA, "第 21 题应为线代大题"
    assert qs[21].question_type == QuestionType.SOLUTION
    assert qs[21].category == ChapterCategory.PROBABILITY, "第 22 题应为概率大题"


def test_math2_standard_exam_slot_restrictions(math2_questions):
    """验证数学二真题标准槽位：1-8高数 9-10线代 11-15高数 16线代 17-21高数 22线代"""
    engine = PaperEngine(math2_questions)
    req = EngineRequest(
        title="2026 考研数学二真题标准模考",
        subject=SubjectType.MATH_2,
        mode=PaperMode.FULL_10_6_6,
        target_chapters=set(MATH_2_CHAPTERS),
        seed=2026,
    )
    paper = engine.generate_single_paper(req)
    assert len(paper.questions) == 22

    qs = paper.questions
    # 选择题 (1~10)
    for i in range(0, 8):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.ADVANCED_MATH, f"题号 {i+1} 应为高数，实际为 {qs[i].category}"
    for i in range(8, 10):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.LINEAR_ALGEBRA, f"题号 {i+1} 应为线代，实际为 {qs[i].category}"

    # 填空题 (11~16)
    for i in range(10, 15):
        assert qs[i].question_type == QuestionType.FILL_BLANK
        assert qs[i].category == ChapterCategory.ADVANCED_MATH, f"题号 {i+1} 应为高数，实际为 {qs[i].category}"
    assert qs[15].question_type == QuestionType.FILL_BLANK
    assert qs[15].category == ChapterCategory.LINEAR_ALGEBRA, "第 16 题应为线代填空"

    # 解答题 (17~22)
    for i in range(16, 21):
        assert qs[i].question_type == QuestionType.SOLUTION
        assert qs[i].category == ChapterCategory.ADVANCED_MATH, f"题号 {i+1} 应为高数，实际为 {qs[i].category}"
    assert qs[21].question_type == QuestionType.SOLUTION
    assert qs[21].category == ChapterCategory.LINEAR_ALGEBRA, "第 22 题应为线代大题"


def test_math3_standard_exam_slot_restrictions(math3_questions):
    """验证数学三真题标准槽位：1-4微积分 5-7线代 8-10概率 11-14微积分 15线代 16概率 17-20微积分 21线代 22概率"""
    engine = PaperEngine(math3_questions)
    req = EngineRequest(
        title="2026 考研数学三真题标准模考",
        subject=SubjectType.MATH_3,
        mode=PaperMode.FULL_10_6_6,
        target_chapters=set(MATH_3_CHAPTERS),
        seed=2026,
    )
    paper = engine.generate_single_paper(req)
    assert len(paper.questions) == 22

    qs = paper.questions
    # 选择题 (1~10)
    for i in range(0, 4):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.ADVANCED_MATH
    for i in range(4, 7):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.LINEAR_ALGEBRA
    for i in range(7, 10):
        assert qs[i].question_type == QuestionType.CHOICE
        assert qs[i].category == ChapterCategory.PROBABILITY

    # 填空题 (11~16)
    for i in range(10, 14):
        assert qs[i].question_type == QuestionType.FILL_BLANK
        assert qs[i].category == ChapterCategory.ADVANCED_MATH
    assert qs[14].category == ChapterCategory.LINEAR_ALGEBRA
    assert qs[15].category == ChapterCategory.PROBABILITY

    # 解答题 (17~22)
    for i in range(16, 20):
        assert qs[i].question_type == QuestionType.SOLUTION
        assert qs[i].category == ChapterCategory.ADVANCED_MATH
    assert qs[20].category == ChapterCategory.LINEAR_ALGEBRA
    assert qs[21].category == ChapterCategory.PROBABILITY


def test_5_3_3_sprint_mode_slots(math1_questions):
    engine = PaperEngine(math1_questions)
    req = EngineRequest(
        title="2026 考研数学速测",
        subject=SubjectType.MATH_1,
        mode=PaperMode.SPRINT_5_3_3,
        target_chapters=set(MATH_1_CHAPTERS),
        seed=2026,
    )
    paper = engine.generate_single_paper(req)
    assert len(paper.questions) == 11
    assert len(paper.choice_questions) == 5
    assert len(paper.fill_questions) == 3
    assert len(paper.solution_questions) == 3


def test_3_paper_bundle_covers_100_percent_math1(math1_questions):
    engine = PaperEngine(math1_questions)
    req = EngineRequest(
        title="2026 考研数学一冲刺",
        subject=SubjectType.MATH_1,
        mode=PaperMode.BUNDLE_3_PAPERS,
        target_chapters=set(MATH_1_CHAPTERS),
        seed=2026,
    )
    bundle = engine.generate_bundle(req, bundle_size=3)
    assert len(bundle.papers) == 3
    for p in bundle.papers:
        assert len(p.questions) == 22
    assert len(bundle.all_covered_chapters) == 23
    assert bundle.total_coverage_ratio == 1.0


def test_3_paper_bundle_covers_100_percent_math2(math2_questions):
    engine = PaperEngine(math2_questions)
    req = EngineRequest(
        title="2026 考研数学二冲刺",
        subject=SubjectType.MATH_2,
        mode=PaperMode.BUNDLE_3_PAPERS,
        target_chapters=set(MATH_2_CHAPTERS),
        seed=2026,
    )
    bundle = engine.generate_bundle(req, bundle_size=3)
    assert len(bundle.papers) == 3
    for p in bundle.papers:
        assert len(p.questions) == 22
    assert len(bundle.all_covered_chapters) == 12
    assert bundle.total_coverage_ratio == 1.0


def test_3_paper_bundle_covers_100_percent_math3(math3_questions):
    engine = PaperEngine(math3_questions)
    req = EngineRequest(
        title="2026 考研数学三冲刺",
        subject=SubjectType.MATH_3,
        mode=PaperMode.BUNDLE_3_PAPERS,
        target_chapters=set(MATH_3_CHAPTERS),
        seed=2026,
    )
    bundle = engine.generate_bundle(req, bundle_size=3)
    assert len(bundle.papers) == 3
    for p in bundle.papers:
        assert len(p.questions) == 22
    assert len(bundle.all_covered_chapters) == 21
    assert bundle.total_coverage_ratio == 1.0


def test_wrong_notebook_state_management(tmp_path):
    mgr = StateManager(data_file=tmp_path / "test_user_wrong.json")
    is_added = mgr.toggle_wrong_question("01-基础-选-01", error_tag="概念模糊", note="定义域忘了对称")
    assert is_added is True
    assert mgr.is_wrong_marked("01-基础-选-01")
    assert mgr.get_wrong_count("01-基础-选-01") == 1

    new_cnt = mgr.increment_wrong_count("01-基础-选-01")
    assert new_cnt == 2
    assert mgr.get_wrong_count("01-基础-选-01") == 2

    mgr.set_wrong_count("01-基础-选-01", 5)
    assert mgr.get_wrong_count("01-基础-选-01") == 5
    assert mgr.is_in_active_pool("01-基础-选-01") is True
    assert "01-基础-选-01" in mgr.get_active_wrong_question_ids()

    mgr.mark_solved_correctly("01-基础-选-01")
    assert mgr.is_in_active_pool("01-基础-选-01") is False
    assert mgr.is_temporarily_mastered("01-基础-选-01") is True
    assert "01-基础-选-01" not in mgr.get_active_wrong_question_ids()

    new_c = mgr.increment_wrong_count("01-基础-选-01")
    assert new_c == 6
    assert mgr.is_in_active_pool("01-基础-选-01") is True
    assert "01-基础-选-01" in mgr.get_active_wrong_question_ids()

    mgr.mark_solved_correctly("01-基础-选-01")
    assert mgr.is_temporarily_mastered("01-基础-选-01") is True

    res = mgr.remove_wrong_question("01-基础-选-01")
    assert res is True
    assert mgr.is_wrong_marked("01-基础-选-01") is False
    assert mgr.is_temporarily_mastered("01-基础-选-01") is False
    assert mgr.is_in_active_pool("01-基础-选-01") is False


def test_pdf_service_three_editions_html_generation(math1_questions):
    from core.pdf_service import PDFEdition, PDFService
    service = PDFService()
    engine = PaperEngine(math1_questions)
    req = EngineRequest(
        title="2026 考研数学模考",
        subject=SubjectType.MATH_1,
        mode=PaperMode.FULL_10_6_6,
        target_chapters=set(MATH_1_CHAPTERS),
        seed=42,
    )
    paper = engine.generate_single_paper(req)
    
    html_real = service.generate_html(paper, edition=PDFEdition.REAL_EXAM)
    assert "2026 年全国硕士研究生招生考试数学" in html_real
    assert "一、选择题" in html_real
    assert "二、填空题" in html_real
    assert "三、解答题" in html_real
    assert "q-card" in html_real

    html_wb = service.generate_html(paper, edition=PDFEdition.WORKBOOK_A4)
    assert "A4 留白做题本" in html_wb
    assert "workspace-box" in html_wb

    html_sol = service.generate_html(paper, edition=PDFEdition.SOLUTION)
    assert "参考答案与详细解析" in html_sol
    assert "solution-block" in html_sol
    assert "【参考答案】" in html_sol


def test_custom_discipline_toggles(math1_questions):
    engine = PaperEngine(math1_questions)

    # 1. 不勾概率（高数 + 线代）：按数二分布 (8+2, 5+1, 5+1)
    req1 = EngineRequest(
        title="高数+线代专练",
        subject=SubjectType.MATH_1,
        mode=PaperMode.FULL_10_6_6,
        target_chapters=set(MATH_1_CHAPTERS),
        enabled_categories={ChapterCategory.ADVANCED_MATH, ChapterCategory.LINEAR_ALGEBRA},
        seed=101,
    )
    p1 = engine.generate_single_paper(req1)
    assert len(p1.questions) == 22
    for i in range(0, 8): assert p1.questions[i].category == ChapterCategory.ADVANCED_MATH
    for i in range(8, 10): assert p1.questions[i].category == ChapterCategory.LINEAR_ALGEBRA
    for i in range(10, 15): assert p1.questions[i].category == ChapterCategory.ADVANCED_MATH
    assert p1.questions[15].category == ChapterCategory.LINEAR_ALGEBRA
    for i in range(16, 21): assert p1.questions[i].category == ChapterCategory.ADVANCED_MATH
    assert p1.questions[21].category == ChapterCategory.LINEAR_ALGEBRA

    # 2. 不勾线代（高数 + 概率）：按数二分布，线代槽位换为概率 (8+2, 5+1, 5+1)
    req2 = EngineRequest(
        title="高数+概率专练",
        subject=SubjectType.MATH_1,
        mode=PaperMode.FULL_10_6_6,
        target_chapters=set(MATH_1_CHAPTERS),
        enabled_categories={ChapterCategory.ADVANCED_MATH, ChapterCategory.PROBABILITY},
        seed=102,
    )
    p2 = engine.generate_single_paper(req2)
    assert len(p2.questions) == 22
    for i in range(0, 8): assert p2.questions[i].category == ChapterCategory.ADVANCED_MATH
    for i in range(8, 10): assert p2.questions[i].category == ChapterCategory.PROBABILITY
    for i in range(10, 15): assert p2.questions[i].category == ChapterCategory.ADVANCED_MATH
    assert p2.questions[15].category == ChapterCategory.PROBABILITY
    for i in range(16, 21): assert p2.questions[i].category == ChapterCategory.ADVANCED_MATH
    assert p2.questions[21].category == ChapterCategory.PROBABILITY

    # 3. 不勾高数（线代 + 概率）：对半分 (5+5, 3+3, 3+3)
    req3 = EngineRequest(
        title="线代+概率专练",
        subject=SubjectType.MATH_1,
        mode=PaperMode.FULL_10_6_6,
        target_chapters=set(MATH_1_CHAPTERS),
        enabled_categories={ChapterCategory.LINEAR_ALGEBRA, ChapterCategory.PROBABILITY},
        seed=103,
    )
    p3 = engine.generate_single_paper(req3)
    assert len(p3.questions) == 22
    for i in range(0, 5): assert p3.questions[i].category == ChapterCategory.LINEAR_ALGEBRA
    for i in range(5, 10): assert p3.questions[i].category == ChapterCategory.PROBABILITY
    for i in range(10, 13): assert p3.questions[i].category == ChapterCategory.LINEAR_ALGEBRA
    for i in range(13, 16): assert p3.questions[i].category == ChapterCategory.PROBABILITY
    for i in range(16, 19): assert p3.questions[i].category == ChapterCategory.LINEAR_ALGEBRA
    for i in range(19, 22): assert p3.questions[i].category == ChapterCategory.PROBABILITY


def test_custom_mode_category_proportions(math1_questions, math2_questions):
    # 1. 自定义配比：10选 6空 4答，高数线代 50:50
    engine1 = PaperEngine(math1_questions)
    req1 = EngineRequest(
        title="自定义配比测试",
        subject=SubjectType.MATH_1,
        mode=PaperMode.CUSTOM,
        target_chapters=set(MATH_1_CHAPTERS),
        type_counts={QuestionType.CHOICE: 10, QuestionType.FILL_BLANK: 6, QuestionType.SOLUTION: 4},
        category_weights={ChapterCategory.ADVANCED_MATH: 50.0, ChapterCategory.LINEAR_ALGEBRA: 50.0},
        seed=888,
    )
    p1 = engine1.generate_single_paper(req1)
    assert len(p1.questions) == 20
    assert len(p1.choice_questions) == 10
    assert len(p1.fill_questions) == 6
    assert len(p1.solution_questions) == 4

    # 验证选择题高数5题、线代5题
    choice_cats = [q.category for q in p1.choice_questions]
    assert choice_cats.count(ChapterCategory.ADVANCED_MATH) == 5
    assert choice_cats.count(ChapterCategory.LINEAR_ALGEBRA) == 5

    # 验证填空题高数3题、线代3题
    fill_cats = [q.category for q in p1.fill_questions]
    assert fill_cats.count(ChapterCategory.ADVANCED_MATH) == 3
    assert fill_cats.count(ChapterCategory.LINEAR_ALGEBRA) == 3

    # 验证数二不包含概率
    engine2 = PaperEngine(math2_questions)
    req2 = EngineRequest(
        title="数二自定义测试",
        subject=SubjectType.MATH_2,
        mode=PaperMode.CUSTOM,
        target_chapters=set(MATH_2_CHAPTERS),
        type_counts={QuestionType.CHOICE: 8, QuestionType.FILL_BLANK: 4, QuestionType.SOLUTION: 4},
        category_weights={ChapterCategory.ADVANCED_MATH: 80.0, ChapterCategory.LINEAR_ALGEBRA: 20.0},
        seed=999,
    )
    p2 = engine2.generate_single_paper(req2)
    assert all(q.category != ChapterCategory.PROBABILITY for q in p2.questions)
