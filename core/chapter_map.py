"""
章节归一化：把各书自带章节名映射到考纲统一章名。

问题：张宇《1000题》按书内细分章组织（高数 18 章 / 线代 9 章 / 概率 9 章，外加测试卷），
与考纲章名（数一 23 章）完全不同名。混在同一科目下会出现 77 个"章节"：
- 章节下拉变成一长串，用户根本找不到目标章；
- 「全章节覆盖」按 77 章算覆盖率，数字失真；
- 组卷选「第十章 行列式」时 1000题 的线代题永远抽不到。

方案（三级，逐级兜底，任一级缺失都不影响运行）：
1. 显式别名表 题库资料/章节别名表.json —— 人工可改，覆盖特例；
2. 关键词规则 —— 按 domain（高数/线代/概率）+ 章节名关键词映射到考纲章；
3. 原名保留 —— 映射不到的原样返回（不丢题，只不归一）。

只改 chapter 字段，不改题号，因此 URL 位图 / canonical 顺序不受影响。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.bank_registry import ALIAS_NAME, bank_root, load_chapter_aliases
from core.models import (
    MATH_1_CHAPTERS,
    MATH_2_CHAPTERS,
    MATH_3_CHAPTERS,
    SubjectType,
)

_CHAPTERS_BY_SUBJECT = {
    SubjectType.MATH_1: MATH_1_CHAPTERS,
    SubjectType.MATH_2: MATH_2_CHAPTERS,
    SubjectType.MATH_3: MATH_3_CHAPTERS,
}

# 关键词规则：(触发词正则, 目标考纲章名里要包含的关键词，按序尝试)
# 顺序敏感：更具体的放前面（如「多维随机变量」必须先于「随机变量及其分布」）。
_GAOSHU_RULES: list[tuple[str, list[str]]] = [
    (r"多元函数积分|曲线积分|曲面积分", ["曲线积分", "多元函数积分"]),
    (r"二重积分|三重积分|重积分", ["二重积分", "重积分"]),
    (r"多元函数微分", ["多元函数微分"]),
    (r"无穷级数|级数", ["无穷级数"]),
    (r"微分方程", ["微分方程"]),
    (r"一元函数积分学|积分学的应用|定积分", ["一元函数积分学"]),
    (r"一元函数微分学|微分学的应用|中值定理", ["一元函数微分学"]),
    (r"数列极限|函数极限|极限与连续|零基础", ["函数、极限、连续", "函数、极限"]),
]

_XIANDAI_RULES: list[tuple[str, list[str]]] = [
    (r"相似|特征值|特征向量", ["相似"]),
    (r"二次型", ["二次型"]),
    (r"线性方程组|方程组", ["线性方程组"]),
    (r"向量组|向量", ["向量"]),
    (r"行列式|余子式|代数余子式", ["行列式"]),
    (r"矩阵的秩|矩阵运算|矩阵", ["矩阵"]),
]

_GAILV_RULES: list[tuple[str, list[str]]] = [
    # 「参数估计与假设检验」这类合并章归参数估计（主考点），故参数估计规则在前
    (r"参数估计", ["参数估计"]),
    (r"假设检验", ["假设检验"]),
    (r"数理统计|统计量", ["数理统计"]),
    (r"大数定律|中心极限", ["大数定律"]),
    (r"数字特征|期望|方差", ["数字特征"]),
    (r"多维随机变量|二维随机变量", ["多维随机变量"]),
    (r"一维随机变量|随机变量及其分布|随机变量函数的分布|随机变量", ["随机变量及其分布"]),
    (r"随机事件|概率", ["随机事件"]),
]

_RULES_BY_DOMAIN = {
    "高数": _GAOSHU_RULES,
    "线代": _XIANDAI_RULES,
    "概率": _GAILV_RULES,
}

_DOMAIN_RE = re.compile(r"^(高数|线代|概率)")


def domain_of(qid: str) -> str:
    """从题号首段取分册 domain（1000题 的 高数-基08-选-01）；非该格式返回 ''。"""
    m = _DOMAIN_RE.match(str(qid or "").strip())
    return m.group(1) if m else ""


def find_chapter(subject: SubjectType, keywords: list[str]) -> str | None:
    """在科目考纲章名表里找第一个包含任一关键词的章名。"""
    chapters = _CHAPTERS_BY_SUBJECT.get(subject, MATH_1_CHAPTERS)
    for kw in keywords:
        for ch in chapters:
            if kw in ch:
                return ch
    return None


class ChapterMapper:
    """章节名归一化器。别名表 > 关键词规则 > 原名。"""

    def __init__(self, subject: SubjectType, root: Path | str | None = None):
        self.subject = subject
        self.root = Path(root) if root else bank_root()
        self.aliases: dict[str, str] = load_chapter_aliases(subject, self.root)

    @classmethod
    def alias_key(cls, domain: str, chapter: str) -> str:
        return f"{domain}|{chapter}" if domain else chapter

    def map(self, chapter: str, qid: str = "") -> str:
        if not chapter:
            return chapter
        domain = domain_of(qid)

        # 1) 显式别名表：先查 domain 限定的键，再查裸章名
        for key in (self.alias_key(domain, chapter), chapter):
            if key in self.aliases:
                return self.aliases[key]

        # 2) 关键词规则
        if domain:
            for pattern, targets in _RULES_BY_DOMAIN.get(domain, []):
                if re.search(pattern, chapter):
                    hit = find_chapter(self.subject, targets)
                    if hit:
                        return hit
        return chapter

    def map_all(self, pairs: list[tuple[str, str]]) -> dict[str, str]:
        """批量：[(qid, chapter)] → {原章节名: 归一章名}"""
        out: dict[str, str] = {}
        for qid, ch in pairs:
            out.setdefault(ch, self.map(ch, qid))
        return out


def write_alias_template(root: Path | str | None = None, path: Path | str | None = None) -> Path:
    """生成/更新别名表骨架（保留已有条目）。供人工维护。"""
    root = Path(root) if root else bank_root()
    target = Path(path) if path else (root / "题库资料" / ALIAS_NAME)
    base: dict[str, dict[str, str]] = {}
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                base = {k: v for k, v in loaded.items() if isinstance(v, dict)}
        except Exception:
            base = {}
    payload = {
        "_说明": "章节别名表：把各书自带章节名映射到考纲统一章名。"
                 "键为『分册|章节名』（1000题等按 高数/线代/概率 分册的书）或裸章节名（880/真题）。"
                 "映射不到的走关键词规则，再不行保留原名。",
        **{s.value: base.get(s.value, {}) for s in _CHAPTERS_BY_SUBJECT},
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
