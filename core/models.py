"""
考研数学智能组卷系统 - 核心数据模型 (Clean-Room 原创实现)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BookType(str, Enum):
    BOOK_880 = "880"


class SubjectType(str, Enum):
    MATH_1 = "数学一"
    MATH_2 = "数学二"
    MATH_3 = "数学三"
    CUSTOM = "自定义"


class ChapterCategory(str, Enum):
    ADVANCED_MATH = "高等数学"
    LINEAR_ALGEBRA = "线性代数"
    PROBABILITY = "概率论与数理统计"


class DifficultyLevel(str, Enum):
    BASIC = "基础题"
    COMPREHENSIVE = "综合题"
    ADVANCED = "拓展题"


class QuestionType(str, Enum):
    CHOICE = "选择题"
    FILL_BLANK = "填空题"
    SOLUTION = "解答题"


class PaperMode(str, Enum):
    FULL_10_6_6 = "10-6-6 全真模考"
    SPRINT_5_3_3 = "5-3-3 速刷精测"
    BUNDLE_3_PAPERS = "3卷全章节覆盖套餐"
    CUSTOM = "自由自定义配比"
    WRONG_NOTEBOOK = "错题本定向巩固"


# 数学一、二、三考纲章节范围映射
MATH_1_CHAPTERS = [
    "第一章 函数、极限、连续",
    "第二章 一元函数微分学及其应用",
    "第三章 一元函数积分学及其应用",
    "第四章 空间解析几何",
    "第五章 多元函数微分学及其应用",
    "第六章 重积分及其应用",
    "第七章 微分方程及其应用",
    "第八章 无穷级数",
    "第九章 曲线积分与曲面积分",
    "第十章 行列式",
    "第十一章 矩阵",
    "第十二章 向量",
    "第十三章 线性方程组",
    "第十四章 相似矩阵",
    "第十五章 二次型",
    "第十六章 随机事件及其概率",
    "第十七章 随机变量及其分布",
    "第十八章 多维随机变量及其分布",
    "第十九章 随机变量的数字特征",
    "第二十章 大数定律与中心极限定理",
    "第二十一章 数理统计的基本概念",
    "第二十二章 参数估计",
    "第二十三章 假设检验",
]

MATH_2_CHAPTERS = [
    "第一章 函数、极限、连续",
    "第二章 一元函数微分学及其应用",
    "第三章 一元函数积分学及其应用",
    "第四章 多元函数微分学及其应用",
    "第五章 二重积分",
    "第六章 微分方程及其应用",
    "第七章 行列式",
    "第八章 矩阵",
    "第九章 向量",
    "第十章 线性方程组",
    "第十一章 相似矩阵",
    "第十二章 二次型",
]

MATH_3_CHAPTERS = [
    "第一章 函数、极限、连续",
    "第二章 一元函数微分学及其应用",
    "第三章 一元函数积分学及其应用",
    "第四章 多元函数微分学及其应用",
    "第五章 二重积分",
    "第六章 微分方程及其应用",
    "第七章 微积分在经济学中的应用",
    "第八章 无穷级数",
    "第九章 行列式",
    "第十章 矩阵",
    "第十一章 向量",
    "第十二章 线性方程组",
    "第十三章 相似矩阵",
    "第十四章 二次型",
    "第十五章 随机事件及其概率",
    "第十六章 随机变量及其分布",
    "第十七章 多维随机变量及其分布",
    "第十八章 随机变量的数字特征",
    "第十九章 大数定律与中心极限定理",
    "第二十章 数理统计的基本概念",
    "第二十一章 参数估计",
]


@dataclass(slots=True)
class QuestionItem:
    """题目完整实体"""
    id: str
    chapter: str
    category: ChapterCategory
    difficulty: DifficultyLevel
    question_type: QuestionType
    core_knowledge: list[str] = field(default_factory=list)
    dimension: str = "技巧计算"
    pitfall_analysis: str = ""
    tags: list[str] = field(default_factory=list)
    recommend_weight: int = 3
    stem: str = ""
    options: list[str] = field(default_factory=list)
    answer: str = ""
    solution: str = ""
    source_file: str = ""
    book: str = "《李林 880 题》"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["difficulty"] = self.difficulty.value
        d["question_type"] = self.question_type.value
        return d


@dataclass(slots=True)
class PaperItem:
    """单套试卷实体"""
    title: str
    paper_id: str
    subject: SubjectType
    mode: PaperMode
    questions: list[QuestionItem]
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    seed: int | None = None
    target_chapters: set[str] = field(default_factory=set)

    @property
    def total_count(self) -> int:
        return len(self.questions)

    @property
    def choice_questions(self) -> list[QuestionItem]:
        return [q for q in self.questions if q.question_type == QuestionType.CHOICE]

    @property
    def fill_questions(self) -> list[QuestionItem]:
        return [q for q in self.questions if q.question_type == QuestionType.FILL_BLANK]

    @property
    def solution_questions(self) -> list[QuestionItem]:
        return [q for q in self.questions if q.question_type == QuestionType.SOLUTION]

    @property
    def covered_chapters(self) -> set[str]:
        return {q.chapter for q in self.questions}

    @property
    def chapter_coverage_ratio(self) -> float:
        if not self.target_chapters:
            return 1.0 if self.covered_chapters else 0.0
        return len(self.covered_chapters & self.target_chapters) / len(self.target_chapters)


@dataclass(slots=True)
class PaperBundle:
    """多卷联合套组（如 A/B/C 三卷组合）"""
    bundle_id: str
    title: str
    subject: SubjectType
    papers: list[PaperItem]
    target_chapters: set[str] = field(default_factory=set)

    @property
    def all_covered_chapters(self) -> set[str]:
        covered: set[str] = set()
        for p in self.papers:
            covered |= p.covered_chapters
        return covered

    @property
    def total_coverage_ratio(self) -> float:
        if not self.target_chapters:
            return 1.0 if self.all_covered_chapters else 0.0
        return len(self.all_covered_chapters & self.target_chapters) / len(self.target_chapters)


@dataclass(slots=True)
class WrongQuestionRecord:
    """错题本记录实体"""
    question_id: str
    added_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    user_note: str = ""
    error_tag: str = "概念模糊"
    wrong_count: int = 1
    is_active_in_pool: bool = True  # True: 待练池; False: 历史错题已掌握
    subject: str = ""  # 科目归属 (如 "数学一", "数学二", "数学三")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
