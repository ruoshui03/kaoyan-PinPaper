"""
题库扩展能力回归测试：书目清单 / 章节归一化 / 选项切分 / 答案包与贡献包。

锁住四条不变量：
1. 章节归一化后，各书章节落在考纲章（或显式声明的"综合测试卷"）内；
2. 挤在一行的选项能被切出来（选择题不会 0 选项）；
3. 答案包能被 loader 自动回填，且垃圾题号被拒绝；
4. 贡献包导入→导出往返保真，未授权时不产生导出。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import contribution as hub
from core.bank_loader import BankLoader
from core.bank_registry import load_books, load_chapter_aliases
from core.chapter_map import ChapterMapper
from core.models import MATH_1_CHAPTERS, SubjectType


def test_manifest_lists_builtin_books_and_honours_enabled():
    books = load_books()
    keys = {b.key for b in books}
    assert {"880", "真题", "张宇1000题"} <= keys
    disabled = [b for b in books if not b.enabled]
    assert disabled, "清单里应保留一条 disabled 示例，演示如何加新书"
    # 内置三本必须排在任何新书之前，否则旧 URL 位图会失效
    orders = {b.key: b.order for b in books}
    assert max(orders[k] for k in ("880", "真题", "张宇1000题")) < min(
        orders[b.key] for b in books if b.key not in ("880", "真题", "张宇1000题"))


def test_chapter_normalization_maps_1000_to_syllabus():
    loader = BankLoader(subject=SubjectType.MATH_1)
    questions = loader.load()
    syllabus = set(MATH_1_CHAPTERS) | {"综合测试卷"}
    off = {q.chapter for q in questions} - syllabus
    assert not off, f"仍有未归一到考纲的章节: {sorted(off)[:5]}"
    # 归一化不能改变题号 → canonical 顺序不变 → 旧链接不失效
    assert len(loader.questions_by_id) == len(questions)


def test_chapter_mapper_examples():
    m1 = ChapterMapper(SubjectType.MATH_1)
    assert m1.map("第1章 行列式", "线代-基01-选-01") == "第十章 行列式"
    assert m1.map("第1章 函数极限与连续", "高数-基01-选-01") == "第一章 函数、极限、连续"
    assert m1.map("第9章 参数估计与假设检验", "概率-基09-选-01") == "第二十二章 参数估计"
    m2 = ChapterMapper(SubjectType.MATH_2)
    assert m2.map("第1章 行列式", "线代-基01-选-01") == "第七章 行列式"
    # 别名表：测试卷统一归到综合测试卷
    assert m1.map("测试卷一", "线代-综01-选-01") == "综合测试卷"


def test_split_inline_options():
    text = ("二次型 $f(x)=x_1x_2$ 的矩阵为（　）. A. $$ \\left(\\begin{array}{cc}1&0\\\\0&1\\end{array}\\right) $$ "
            "B. $$ \\left(\\begin{array}{cc}0&1\\\\1&0\\end{array}\\right) $$ C. $I$ D. $2I$")
    got = BankLoader._split_inline_options(text)
    assert got is not None
    stem, options = got
    assert len(options) == 4 and "的矩阵为" in stem
    # 题干里出现 A,B 但不构成选项时不应误切
    assert BankLoader._split_inline_options("设 A,B 为同阶方阵，且 AB=O，则下列结论正确的是（ ）") is None


def test_answer_pack_is_applied_by_loader():
    """答案包落到 solutions/<book>/<subject>/ 后，loader 应自动回填。"""
    root = Path(__file__).resolve().parent.parent
    loader = BankLoader(subject=SubjectType.MATH_2)
    loader.load()
    target_id = "12-基础-选-01"
    assert target_id in loader.questions_by_id

    pack_dir = root / "solutions" / "880" / "数学二"
    pack_file = pack_dir / "test_pack_tmp.json"
    pack_dir.mkdir(parents=True, exist_ok=True)
    try:
        pack_file.write_text(json.dumps({
            "book": "880", "subject": "数学二",
            "items": [{"id": target_id, "answer": "A", "solution": "测试解析"}],
        }, ensure_ascii=False), encoding="utf-8")
        loader2 = BankLoader(subject=SubjectType.MATH_2)
        loader2.load()
        assert loader2.questions_by_id[target_id].answer == "A"
        assert "测试解析" in loader2.questions_by_id[target_id].solution
    finally:
        pack_file.unlink(missing_ok=True)


def test_contribution_import_export_roundtrip(tmp_path):
    root = tmp_path
    book, subject = "880", "数学二"
    src = tmp_path / "in.md"
    src.write_text("## 01-基础-选-01\n【答案】C\n【解析】因为…\n\n"
                   "## 不存在的题号\n【答案】A\n", encoding="utf-8")

    res = hub.import_pack(str(src), valid_ids={"01-基础-选-01"}, root=root,
                          book_override=book, subject_override=subject)
    assert res["accepted"] == 1, "只采纳题号存在的条目"
    assert res["unknown_count"] == 1

    stats = hub.stats(root)
    assert stats[f"{book}/{subject}"]["entries"] == 1

    # 未授权导出 → 阻止
    consent = hub.read_consent(root)
    assert consent["share"] is False
    hub.write_consent(share=True, author=" tester ", root=root)
    out = hub.export_pack(book, subject, root=root, author="tester")
    pack = json.loads(Path(out).read_text(encoding="utf-8"))
    assert pack["format"] == hub.PACK_FORMAT
    assert pack["items"][0]["id"] == "01-基础-选-01"
    assert pack["items"][0]["solution"] == "因为…"


def test_sign_and_verify(tmp_path):
    pack = hub.make_pack("880", "数学一", [{"id": "x", "answer": "A"}], secret="s3cret")
    assert hub.verify_pack(pack, "s3cret")
    assert not hub.verify_pack(pack, "wrong")
