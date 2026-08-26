"""
URL 位图与书籍隔离单元测试

验证三件事：
1. 今天整科==880，canonical_ids("880") 与全量题号完全相等（零行为变化）；
2. 将来加第二本书不会动 880 的位图列表/签名（护住旧 URL 的核心目标）；
3. 位图 roundtrip 三态（待练/顽固/历史）保真（回归现有编码行为）。
"""
from __future__ import annotations

import tempfile

import pytest

from core.bank_loader import BankLoader
from core.models import QuestionItem, ChapterCategory, DifficultyLevel, QuestionType, SubjectType
from core.state_manager import StateManager


@pytest.mark.parametrize("subject", [SubjectType.MATH_1, SubjectType.MATH_2, SubjectType.MATH_3])
def test_canonical_ids_880_equals_full_today(subject):
    """今天整科只有 880，按书过滤应与全量题号完全一致（顺序也一致）。"""
    loader = BankLoader(subject=subject)
    loader.load()
    assert loader.canonical_ids(book="880") == list(loader.questions_by_id.keys())
    assert loader.canonical_ids() == list(loader.questions_by_id.keys())


def test_second_book_does_not_shift_880_bitmap():
    """向题库注入一条第二本书的假题后，880 的 canonical 列表与签名必须保持不变。

    这直接验证「加第二本书不会使 880 的旧 URL 失效」这一核心目标。
    """
    loader = BankLoader(subject=SubjectType.MATH_1)
    loader.load()

    ids_before = loader.canonical_ids(book="880")
    sig_before = StateManager.bank_signature(ids_before)

    # 注入一条第二本书的题（沿用一个已存在的题号，模拟"撞号"最坏情况）
    ghost_id = ids_before[0]
    loader.questions_by_id["__ghost__"] = QuestionItem(
        id=ghost_id,
        chapter="第一章 函数、极限、连续",
        category=ChapterCategory.ADVANCED_MATH,
        difficulty=DifficultyLevel.BASIC,
        question_type=QuestionType.CHOICE,
        book="测试书",
    )

    ids_after = loader.canonical_ids(book="880")
    sig_after = StateManager.bank_signature(ids_after)

    assert ids_after == ids_before, "880 的题号列表被第二本书改变了"
    assert sig_after == sig_before, "880 的位图签名被第二本书改变了（旧 URL 会失效）"


def test_bitmap_roundtrip_preserves_three_states():
    """位图 roundtrip：待练 / 顽固(≥2) / 历史 三态保真。"""
    loader = BankLoader(subject=SubjectType.MATH_1)
    loader.load()
    ordered = loader.canonical_ids(book="880")

    sm = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    pending, stubborn, mastered = ordered[0], ordered[1], ordered[2]
    sm.batch_mark_wrong([pending, stubborn, mastered])  # 三题先入待练(wrong_count>0)
    sm.increment_wrong_count(stubborn, 2)               # → 顽固 (≥2)
    sm.mark_solved_correctly(mastered)                  # 归档为历史(仍 wrong_count>0)

    code = sm.to_url_code(ordered)
    assert code.startswith("w2~")

    sm2 = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    n, status = sm2.apply_url_code(code, ordered)
    assert status == "ok" and n == 3

    assert sm2.is_in_active_pool(pending) and sm2.get_wrong_count(pending) < 2   # 待练
    assert sm2.is_in_active_pool(stubborn) and sm2.get_wrong_count(stubborn) >= 2  # 顽固
    assert sm2.is_temporarily_mastered(mastered)                                 # 历史


def test_stale_signature_rejected():
    """题号列表变化后，旧 code 应被判 stale 并拒绝套用。"""
    loader = BankLoader(subject=SubjectType.MATH_1)
    loader.load()
    ordered = loader.canonical_ids(book="880")

    sm = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    sm.batch_mark_wrong(ordered[:3])
    code = sm.to_url_code(ordered)

    sm2 = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    n, status = sm2.apply_url_code(code, ordered[:-1])  # 少一题 → 签名不匹配
    assert status == "stale" and n == 0


def test_fingerprint_signature_survives_id_rename():
    """签名依据用题干指纹时,改题号(顺序/内容不变)不应使 code 失效。"""
    loader = BankLoader(subject=SubjectType.MATH_1)
    loader.load()
    ordered = loader.canonical_ids(book="880")
    fp = loader.canonical_fingerprints(book="880")

    sm = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    sm.batch_mark_wrong([ordered[0], ordered[5], ordered[9]])
    code = sm.to_url_code(ordered, sig_basis=fp)

    # 模拟一次题号改写:ID 全变(加后缀),但顺序与题干指纹不变
    renamed = [q + "-X" for q in ordered]

    sm2 = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    n, status = sm2.apply_url_code(code, renamed, sig_basis=fp)
    assert status == "ok" and n == 3
    # 恢复的错题落在改写后的新题号上(按位置对齐)
    assert sm2.is_wrong_marked(renamed[0])
    assert sm2.is_wrong_marked(renamed[5])
    assert sm2.is_wrong_marked(renamed[9])


def test_fingerprint_signature_detects_content_change():
    """题干内容变化(增删/改题面)仍应被指纹签名捕获为 stale。"""
    loader = BankLoader(subject=SubjectType.MATH_1)
    loader.load()
    ordered = loader.canonical_ids(book="880")
    fp = loader.canonical_fingerprints(book="880")

    sm = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    sm.batch_mark_wrong(ordered[:3])
    code = sm.to_url_code(ordered, sig_basis=fp)

    fp_changed = fp[:-1]  # 少一题 → 指纹列表变 → 签名变
    sm2 = StateManager(data_file=tempfile.mktemp(suffix=".json"), subject=SubjectType.MATH_1)
    n, status = sm2.apply_url_code(code, ordered[:-1], sig_basis=fp_changed)
    assert status == "stale" and n == 0
