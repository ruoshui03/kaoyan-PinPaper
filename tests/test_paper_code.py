"""
试卷码（URL q1/q2/q3）单元测试

回归的真实缺陷：旧 p1 格式把索引锚定在 880 单本 canonical 上，凡是 880 以外的题
（真题 / 张宇1000题）在编码时被**静默丢弃**，且解码仍返回 'ok'。结果是"生成卷子后
刷新，卷子只剩 880 那部分"——因为错题多标在 880，看起来就像"只剩错题"。

本文件锁住四条不变量：
1. 跨书试卷 roundtrip 完全保真（缺陷本体）；
2. 旧 p1 链接仍可解（不砸历史链接）；
3. 加第四本书不影响只引用前三本的旧 p2 码（URL 不失效红线）；
4. 被引用的书本身变了要判 stale，未被引用的书变了不受影响。
"""
from __future__ import annotations

import base64
import zlib

import pytest

from core.bank_loader import BankLoader
from core.models import SubjectType
from core.state_manager import StateManager

BOOK_880 = "880"
BOOK_ZT = "真题2010-2026"
BOOK_1K = "张宇1000题"


@pytest.fixture(scope="module")
def loader():
    lo = BankLoader(subject=SubjectType.MATH_2)
    lo.load()
    return lo


@pytest.fixture(scope="module")
def book_canonicals(loader):
    return {
        BOOK_880: loader.canonical_ids(book=BOOK_880),
        BOOK_ZT: loader.canonical_ids(book=BOOK_ZT),
        BOOK_1K: loader.canonical_ids(book=BOOK_1K),
    }


@pytest.fixture(scope="module")
def ids_by_book(book_canonicals):
    # 每本书取够用的题号；书为空则跳过相关用例
    return {b: ids for b, ids in book_canonicals.items() if ids}


def test_mixed_book_paper_roundtrip_is_lossless(book_canonicals, ids_by_book):
    """核心回归：一份跨三本书的卷子编码再解码，题号与顺序必须一模一样。"""
    paper = []
    for ids in ids_by_book.values():
        paper += ids[:4]
    assert len(paper) >= 8, "题库里至少要有两本非空的书才测得出跨书丢题"

    code = StateManager.encode_papers_code([paper], book_canonicals)
    decoded, status = StateManager.decode_papers_code(code, book_canonicals)

    assert status == "ok"
    assert decoded[0] == paper, "跨书试卷必须完整还原，一题都不许丢"


def test_pure_non_880_paper_survives(book_canonicals, ids_by_book):
    """极端情形：整卷都不含 880（如纯真题卷）。旧格式会还原成空卷。"""
    zt = ids_by_book.get(BOOK_ZT)
    if not zt:
        pytest.skip("题库里没有真题")
    paper = zt[:22]
    code = StateManager.encode_papers_code([paper], book_canonicals)
    decoded, status = StateManager.decode_papers_code(code, book_canonicals)
    assert status == "ok"
    assert decoded[0] == paper and len(decoded[0]) == 22


def test_multi_paper_bundle_roundtrip(book_canonicals, ids_by_book):
    """3 套联考：每卷各自跨书，卷数与卷内顺序都要保真。"""
    books = list(ids_by_book.values())
    papers = [books[i % len(books)][: 10 - i * 2] for i in range(3)]
    code = StateManager.encode_papers_code(papers, book_canonicals)
    decoded, status = StateManager.decode_papers_code(code, book_canonicals)
    assert status == "ok"
    assert decoded == papers


def test_legacy_p1_code_still_decodes(book_canonicals):
    """旧 p1 链接（索引锚 880）必须仍能解出原卷，不砸历史链接。"""
    c880 = book_canonicals[BOOK_880]
    paper = c880[:12]
    index_of = {q: i for i, q in enumerate(c880)}
    body = bytearray([1, len(paper)])
    for q in paper:
        body += index_of[q].to_bytes(2, "little")
    b64 = base64.urlsafe_b64encode(zlib.compress(bytes(body), 9)).decode("ascii").rstrip("=")
    old_code = f"p1~{StateManager.bank_signature(c880)}~{b64}"

    decoded, status = StateManager.decode_papers_code(
        old_code, book_canonicals, legacy_ordered_ids=c880
    )
    assert status == "ok"
    assert decoded[0] == paper


def test_adding_a_fourth_book_does_not_invalidate_existing_code(book_canonicals, ids_by_book):
    """URL 不失效红线：将来接入第四本书，只引用前三本的旧码必须照样有效。"""
    zt = ids_by_book.get(BOOK_ZT)
    if not zt:
        pytest.skip("题库里没有真题")
    paper = book_canonicals[BOOK_880][:6] + zt[:6]
    code = StateManager.encode_papers_code([paper], book_canonicals)

    new_book = "某第四本书"
    plus = dict(book_canonicals)
    plus[new_book] = ["NEW-001", "NEW-002"]
    original_codes = dict(StateManager.PAPER_BOOK_CODES)
    try:
        StateManager.PAPER_BOOK_CODES[new_book] = 4
        decoded, status = StateManager.decode_papers_code(code, plus)
    finally:
        StateManager.PAPER_BOOK_CODES.clear()
        StateManager.PAPER_BOOK_CODES.update(original_codes)

    assert status == "ok"
    assert decoded[0] == paper


def test_changed_referenced_book_is_stale(book_canonicals, ids_by_book):
    """被引用的书 canonical 变了 → 必须判 stale，宁可不恢复也不能错位。"""
    zt = ids_by_book.get(BOOK_ZT)
    if not zt:
        pytest.skip("题库里没有真题")
    paper = book_canonicals[BOOK_880][:6] + zt[:6]
    code = StateManager.encode_papers_code([paper], book_canonicals)

    tampered = dict(book_canonicals)
    tampered[BOOK_ZT] = zt[:-1]
    decoded, status = StateManager.decode_papers_code(code, tampered)
    assert status == "stale"
    assert decoded == []


def test_changed_unreferenced_book_does_not_affect_code(book_canonicals, ids_by_book):
    """未被引用的书变了 → 与本码无关，必须仍然 ok。"""
    k1 = ids_by_book.get(BOOK_1K)
    if not k1:
        pytest.skip("题库里没有 1000 题")
    paper = book_canonicals[BOOK_880][:8]  # 只引用 880
    code = StateManager.encode_papers_code([paper], book_canonicals)

    tampered = dict(book_canonicals)
    tampered[BOOK_1K] = k1[:-5]
    decoded, status = StateManager.decode_papers_code(code, tampered)
    assert status == "ok"
    assert decoded[0] == paper


def test_malformed_code_is_invalid(book_canonicals):
    """格式不对的码不能抛异常，也不能被当成有效卷。"""
    for bad in ("", "garbage", "p2~onlytwo", "p9~abcd1234~zzzz", "p2~abcd1234~!!!not-b64!!!"):
        decoded, status = StateManager.decode_papers_code(bad, book_canonicals)
        assert decoded == []
        assert status in ("invalid", "stale")
