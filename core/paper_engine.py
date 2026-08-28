"""
考研数学智能组卷系统 - 真题大纲规范槽位映射与组卷引擎
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from core.bank_loader import parse_chapter_number, parse_qid_tuple
from core.models import (
    ChapterCategory,
    DifficultyLevel,
    PaperBundle,
    PaperItem,
    PaperMode,
    QuestionItem,
    QuestionType,
    SubjectType,
)


@dataclass(slots=True)
class ExamSlot:
    index: int
    question_type: QuestionType
    category: ChapterCategory
    description: str = ""


@dataclass(slots=True)
class EngineRequest:
    title: str
    subject: SubjectType
    mode: PaperMode
    target_chapters: set[str]
    enabled_categories: set[ChapterCategory] | None = None
    type_counts: dict[QuestionType, int] = field(default_factory=dict)
    category_weights: dict[ChapterCategory, float] = field(default_factory=dict)
    difficulty_weights: dict[DifficultyLevel, float] = field(default_factory=dict)
    tag_filter: str = "全部"
    seed: int | None = None
    historical_covered_chapters: set[str] = field(default_factory=set)
    historical_seen_question_ids: set[str] = field(default_factory=set)
    candidate_question_pool: list[QuestionItem] | None = None
    # 错题优先池与占比：每个题型槽位先按 priority_ratio 从错题池抽，剩余用新题补；
    # 任一侧不足时由另一侧自动补齐。ratio<=0 或池为空 → 退化为普通全书抽题。
    priority_pool_ids: set[str] = field(default_factory=set)
    priority_ratio: float = 0.0
    # 是否排除"已抽过的新题"(seen)。仅作用于新题池，错题优先池不受影响；
    # 过滤后新题不足时软重置(回退完整新题池)。见 historical_seen_question_ids。
    exclude_seen: bool = True
    # 真题章节分布软权重:{题型: {章名: 权重}}。抽题打分时乘上当前题(题型+章)的权重,
    # 缺省 1.0(不影响)。真题里考得多的章权重>1 → 880 组卷更易抽中。空 dict = 不启用。
    chapter_weights: dict[str, dict[str, float]] = field(default_factory=dict)


def get_standard_slots(
    subject: SubjectType,
    mode: PaperMode,
    enabled_categories: set[ChapterCategory] | None = None,
) -> list[ExamSlot]:
    if enabled_categories is None:
        if subject == SubjectType.MATH_2:
            enabled_categories = {ChapterCategory.ADVANCED_MATH, ChapterCategory.LINEAR_ALGEBRA}
        else:
            enabled_categories = {
                ChapterCategory.ADVANCED_MATH,
                ChapterCategory.LINEAR_ALGEBRA,
                ChapterCategory.PROBABILITY,
            }

    has_math = ChapterCategory.ADVANCED_MATH in enabled_categories
    has_linalg = ChapterCategory.LINEAR_ALGEBRA in enabled_categories
    has_prob = ChapterCategory.PROBABILITY in enabled_categories

    if mode in (PaperMode.FULL_10_6_6, PaperMode.BUNDLE_3_PAPERS):
        slots: list[ExamSlot] = []

        if has_math and has_linalg and has_prob:
            for i in range(1, 5):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            for i in range(5, 8):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(8, 11):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            for i in range(11, 15):
                slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(15, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            slots.append(ExamSlot(16, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            for i in range(17, 21):
                slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(21, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            slots.append(ExamSlot(22, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

        elif has_math and has_linalg and not has_prob:
            for i in range(1, 9):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            for i in range(9, 11):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(11, 16):
                slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(16, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(17, 22):
                slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(22, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            return slots

        elif has_math and not has_linalg and has_prob:
            for i in range(1, 9):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            for i in range(9, 11):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            for i in range(11, 16):
                slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(16, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            for i in range(17, 22):
                slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(22, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

        elif not has_math and has_linalg and has_prob:
            for i in range(1, 6):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(6, 11):
                slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            for i in range(11, 14):
                slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(14, 17):
                slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            for i in range(17, 20):
                slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(20, 23):
                slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

        elif has_math:
            for i in range(1, 11): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            for i in range(11, 17): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            for i in range(17, 23): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            return slots
        elif has_linalg:
            for i in range(1, 11): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(11, 17): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(17, 23): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            return slots
        elif has_prob:
            for i in range(1, 11): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            for i in range(11, 17): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            for i in range(17, 23): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

    elif mode == PaperMode.SPRINT_5_3_3:
        slots: list[ExamSlot] = []

        if has_math and has_linalg and has_prob:
            for i in range(1, 4): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(4, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            slots.append(ExamSlot(5, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            slots.append(ExamSlot(6, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(7, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            slots.append(ExamSlot(8, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            slots.append(ExamSlot(9, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(10, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            slots.append(ExamSlot(11, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

        elif has_math and has_linalg and not has_prob:
            for i in range(1, 5): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(5, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(6, 8): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(8, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(9, 11): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(11, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            return slots

        elif has_math and not has_linalg and has_prob:
            for i in range(1, 5): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(5, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            for i in range(6, 8): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(8, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            for i in range(9, 11): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            slots.append(ExamSlot(11, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

        elif not has_math and has_linalg and has_prob:
            for i in range(1, 4): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(4, 6): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            for i in range(6, 8): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            slots.append(ExamSlot(8, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            for i in range(9, 11): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            slots.append(ExamSlot(11, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

        elif has_math:
            for i in range(1, 6): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.ADVANCED_MATH))
            for i in range(6, 9): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.ADVANCED_MATH))
            for i in range(9, 12): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.ADVANCED_MATH))
            return slots
        elif has_linalg:
            for i in range(1, 6): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(6, 9): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.LINEAR_ALGEBRA))
            for i in range(9, 12): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.LINEAR_ALGEBRA))
            return slots
        elif has_prob:
            for i in range(1, 6): slots.append(ExamSlot(i, QuestionType.CHOICE, ChapterCategory.PROBABILITY))
            for i in range(6, 9): slots.append(ExamSlot(i, QuestionType.FILL_BLANK, ChapterCategory.PROBABILITY))
            for i in range(9, 12): slots.append(ExamSlot(i, QuestionType.SOLUTION, ChapterCategory.PROBABILITY))
            return slots

    return []


class PaperEngine:

    TYPE_ORDER = (QuestionType.CHOICE, QuestionType.FILL_BLANK, QuestionType.SOLUTION)
    CATEGORY_ORDER = (ChapterCategory.ADVANCED_MATH, ChapterCategory.LINEAR_ALGEBRA, ChapterCategory.PROBABILITY)

    def __init__(self, all_questions: Sequence[QuestionItem]):
        self.all_questions = list(all_questions)

    def generate_single_paper(self, request: EngineRequest) -> PaperItem:
        rng = random.Random(request.seed)
        target_chapters = set(request.target_chapters) if request.target_chapters else {q.chapter for q in self.all_questions}

        standard_slots = get_standard_slots(request.subject, request.mode, request.enabled_categories)
        if standard_slots and request.mode != PaperMode.CUSTOM:
            return self._generate_with_slots(request, standard_slots, rng)

        return self._generate_custom_paper(request, rng)

    def _generate_with_slots(self, request: EngineRequest, slots: list[ExamSlot], rng: random.Random) -> PaperItem:
        target_chapters = set(request.target_chapters) if request.target_chapters else {q.chapter for q in self.all_questions}
        base_pool = self._filter_pool(
            source_questions=request.candidate_question_pool or self.all_questions,
            target_chapters=target_chapters,
            tag_filter=request.tag_filter,
            difficulty_weights=request.difficulty_weights,
        )

        globally_selected_ids: set[str] = set()
        chapter_usage: Counter[str] = Counter()
        covered_knowledge: Counter[str] = Counter()
        unseen_chapters = target_chapters - request.historical_covered_chapters

        slot_groups: dict[tuple[QuestionType, ChapterCategory], list[ExamSlot]] = defaultdict(list)
        for s in slots:
            slot_groups[(s.question_type, s.category)].append(s)

        ordered_final_questions: list[QuestionItem] = []

        for (qtype, cat), group_slots in slot_groups.items():
            needed = len(group_slots)
            cat_pool = [
                q for q in base_pool
                if q.question_type == qtype
                and q.category == cat
                and q.id not in globally_selected_ids
            ]

            if len(cat_pool) < needed and request.tag_filter != "全部":
                fallback_pool = [
                    q for q in (request.candidate_question_pool or self.all_questions)
                    if q.chapter in target_chapters
                    and q.question_type == qtype
                    and q.category == cat
                    and q.id not in globally_selected_ids
                    and request.difficulty_weights.get(q.difficulty, 1.0) > 0
                ]
                for q in fallback_pool:
                    if q not in cat_pool:
                        cat_pool.append(q)

            chosen_for_group = self._pick_priority_then_fill(
                cat_pool, needed, request, unseen_chapters,
                chapter_usage, covered_knowledge, globally_selected_ids, rng,
            )

            chosen_for_group.sort(key=lambda q: (
                parse_chapter_number(q.chapter, q.id),
                (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED).index(q.difficulty) if q.difficulty in (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED) else 1,
                parse_qid_tuple(q.id),
            ))

            ordered_final_questions.extend(chosen_for_group)

        paper_id = f"880-{request.subject.value}-{int(request.seed or rng.randint(1000, 9999))}"
        return PaperItem(
            title=request.title,
            paper_id=paper_id,
            subject=request.subject,
            mode=request.mode,
            questions=ordered_final_questions,
            seed=request.seed or rng.randint(100, 99999),
            target_chapters=set(target_chapters),
        )

    def _generate_custom_paper(self, request: EngineRequest, rng: random.Random) -> PaperItem:
        target_chapters = set(request.target_chapters) if request.target_chapters else {q.chapter for q in self.all_questions}
        counts = self._resolve_type_counts(request.mode, request.type_counts)
        base_pool = self._filter_pool(
            source_questions=request.candidate_question_pool or self.all_questions,
            target_chapters=target_chapters,
            tag_filter=request.tag_filter,
            difficulty_weights=request.difficulty_weights,
        )

        selected: list[QuestionItem] = []
        selected_ids: set[str] = set()
        chapter_usage: Counter[str] = Counter()
        covered_knowledge: Counter[str] = Counter()
        unseen_chapters = target_chapters - request.historical_covered_chapters

        # 检查是否配置了学科比例
        cat_weights = {k: max(0.0, v) for k, v in request.category_weights.items()} if request.category_weights else {}
        total_w = sum(cat_weights.values())

        if total_w > 0:
            # 按照配置的学科比例分配各题型名额
            for qtype in self.TYPE_ORDER:
                needed = counts.get(qtype, 0)
                if needed <= 0:
                    continue

                active_cats = [c for c in self.CATEGORY_ORDER if cat_weights.get(c, 0.0) > 0]
                if not active_cats:
                    active_cats = list(self.CATEGORY_ORDER)

                # 计算各学科分配数量
                allocated: dict[ChapterCategory, int] = {}
                remain = needed
                for c in active_cats:
                    alloc = int(round(needed * (cat_weights.get(c, 0.0) / total_w)))
                    allocated[c] = alloc
                # 调整舍入误差
                diff = needed - sum(allocated.values())
                if diff != 0 and active_cats:
                    max_cat = max(active_cats, key=lambda c: cat_weights.get(c, 0.0))
                    allocated[max_cat] = max(0, allocated[max_cat] + diff)

                for cat in active_cats:
                    cat_need = allocated.get(cat, 0)
                    if cat_need <= 0:
                        continue
                    cat_pool = [q for q in base_pool if q.question_type == qtype and q.category == cat and q.id not in selected_ids]
                    picked = self._pick_priority_then_fill(
                        cat_pool, cat_need, request, unseen_chapters,
                        chapter_usage, covered_knowledge, selected_ids, rng,
                    )
                    selected.extend(picked)
        else:
            # 常规自由抽选
            for qtype in self.TYPE_ORDER:
                needed = counts.get(qtype, 0)
                if needed <= 0:
                    continue

                type_pool = [q for q in base_pool if q.question_type == qtype and q.id not in selected_ids]
                picked = self._pick_priority_then_fill(
                    type_pool, needed, request, unseen_chapters,
                    chapter_usage, covered_knowledge, selected_ids, rng,
                )
                selected.extend(picked)

        diff_order = (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED)
        selected.sort(key=lambda q: (
            self.TYPE_ORDER.index(q.question_type) if q.question_type in self.TYPE_ORDER else 9,
            self.CATEGORY_ORDER.index(q.category) if q.category in self.CATEGORY_ORDER else 9,
            parse_chapter_number(q.chapter, q.id),
            diff_order.index(q.difficulty) if q.difficulty in diff_order else 9,
            q.id,
        ))

        paper_id = f"880-{request.subject.value}-{int(request.seed or rng.randint(1000, 9999))}"
        return PaperItem(
            title=request.title,
            paper_id=paper_id,
            subject=request.subject,
            mode=request.mode,
            questions=selected,
            seed=request.seed or rng.randint(100, 99999),
            target_chapters=set(target_chapters),
        )

    def generate_bundle(self, request: EngineRequest, bundle_size: int = 3) -> PaperBundle:
        rng = random.Random(request.seed)
        target_chapters = sorted(list(request.target_chapters)) if request.target_chapters else sorted(list({q.chapter for q in self.all_questions}))

        cat_to_chapters: dict[ChapterCategory, list[str]] = defaultdict(list)
        for ch in target_chapters:
            matching_q = next((q for q in self.all_questions if q.chapter == ch), None)
            if matching_q:
                cat_to_chapters[matching_q.category].append(ch)

        cat_buckets: dict[ChapterCategory, list[set[str]]] = {}
        for cat, ch_list in cat_to_chapters.items():
            shuffled = list(ch_list)
            rng.shuffle(shuffled)
            buckets = [set() for _ in range(bundle_size)]
            for i, ch in enumerate(shuffled):
                buckets[i % bundle_size].add(ch)
            cat_buckets[cat] = buckets

        papers: list[PaperItem] = []
        globally_selected_ids: set[str] = set()
        globally_covered_chapters: set[str] = set()
        alphabet = ["A", "B", "C", "D", "E"]

        standard_slots = get_standard_slots(request.subject, PaperMode.FULL_10_6_6, request.enabled_categories)

        for idx in range(bundle_size):
            sub_seed = (request.seed or 1000) + idx * 7919
            sub_rng = random.Random(sub_seed)

            paper_selected: list[QuestionItem] = []
            slot_groups: dict[tuple[QuestionType, ChapterCategory], list[ExamSlot]] = defaultdict(list)
            for s in standard_slots:
                slot_groups[(s.question_type, s.category)].append(s)

            chapter_usage: Counter[str] = Counter()
            covered_knowledge: Counter[str] = Counter()

            for (qtype, cat), group_slots in slot_groups.items():
                needed = len(group_slots)
                cat_assigned = cat_buckets.get(cat, [set()]*bundle_size)[idx]
                uncovered_in_cat = set(cat_to_chapters.get(cat, [])) - globally_covered_chapters

                cat_pool = [
                    q for q in self.all_questions
                    if q.question_type == qtype
                    and q.category == cat
                    and q.chapter in target_chapters
                    and q.id not in globally_selected_ids
                ]

                chosen_for_group: list[QuestionItem] = []

                priority_pool = [
                    q for q in cat_pool
                    if q.chapter in cat_assigned or q.chapter in uncovered_in_cat
                ]
                sub_rng.shuffle(priority_pool)

                while priority_pool and len(chosen_for_group) < needed:
                    q = priority_pool.pop()
                    if q in cat_pool:
                        cat_pool.remove(q)
                    chosen_for_group.append(q)
                    globally_selected_ids.add(q.id)
                    globally_covered_chapters.add(q.chapter)
                    chapter_usage[q.chapter] += 1
                    covered_knowledge.update(q.core_knowledge)

                while len(chosen_for_group) < needed and cat_pool:
                    scores = [
                        self._compute_score(
                            question=q,
                            difficulty_weight=request.difficulty_weights.get(q.difficulty, 1.0),
                            is_historically_uncovered=q.chapter not in globally_covered_chapters,
                            current_chapter_count=chapter_usage[q.chapter],
                            seen_knowledge=covered_knowledge,
                            chapter_weight=request.chapter_weights.get(
                                q.question_type.value, {}).get(q.chapter, 1.0),
                        )
                        for q in cat_pool
                    ]
                    chosen_idx = self._roulette_select(scores, sub_rng)
                    chosen_q = cat_pool.pop(chosen_idx)

                    chosen_for_group.append(chosen_q)
                    globally_selected_ids.add(chosen_q.id)
                    globally_covered_chapters.add(chosen_q.chapter)
                    chapter_usage[chosen_q.chapter] += 1
                    covered_knowledge.update(chosen_q.core_knowledge)

                chosen_for_group.sort(key=lambda q: (
                    parse_chapter_number(q.chapter, q.id),
                    (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED).index(q.difficulty) if q.difficulty in (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED) else 1,
                    parse_qid_tuple(q.id),
                ))
                paper_selected.extend(chosen_for_group)

            paper = PaperItem(
                title=f"{request.title}（{alphabet[idx]}卷）",
                paper_id=f"880-{request.subject.value}-{sub_seed}",
                subject=request.subject,
                mode=PaperMode.FULL_10_6_6,
                questions=paper_selected,
                seed=sub_seed,
                target_chapters=set(target_chapters),
            )
            papers.append(paper)

        # 全章节覆盖兜底：加权抽取可能遗漏个别窄槽位章节（如"参数估计"仅有解答题），
        # 此处对仍未覆盖的目标章节做一次结构无损换入，确保 3 卷严格 100% 覆盖。
        self._ensure_bundle_coverage(papers, target_chapters, globally_selected_ids, globally_covered_chapters)

        bundle_title = f"{request.title}（3卷全章节覆盖套餐）" if "套餐" not in request.title else request.title
        return PaperBundle(
            bundle_id=f"BUNDLE-{request.subject.value}-{request.seed or rng.randint(1000, 9999)}",
            title=bundle_title,
            subject=request.subject,
            papers=papers,
            target_chapters=set(target_chapters),
        )

    def _ensure_bundle_coverage(
        self,
        papers: list[PaperItem],
        target_chapters: list[str],
        globally_selected_ids: set[str],
        globally_covered_chapters: set[str],
    ) -> None:
        """结构无损地补齐套餐遗漏的目标章节。

        对每个未覆盖章节，取其一道未被选用的代表题，换掉某张卷中"同题型且该章节已重复覆盖"
        的冗余题：优先同学科（不改变学科配比），否则退化为同题型任意冗余题。若无处可换则跳过。
        换入后保持每卷题量与 10-6-6 题型结构不变。
        """
        uncovered = [ch for ch in target_chapters if ch not in globally_covered_chapters]
        if not uncovered:
            return

        # 目标章节 -> 学科映射，供同学科优先匹配
        chapter_category: dict[str, ChapterCategory] = {}
        for ch in target_chapters:
            mq = next((q for q in self.all_questions if q.chapter == ch), None)
            if mq:
                chapter_category[ch] = mq.category

        for ch in uncovered:
            # 该章节可换入的候选题（尚未被套餐选用）
            incoming_candidates = [
                q for q in self.all_questions
                if q.chapter == ch and q.id not in globally_selected_ids
            ]
            if not incoming_candidates:
                continue

            swapped = False
            # 依次尝试各题型的候选，直到找到可换入的卷面冗余位
            for incoming in incoming_candidates:
                qtype = incoming.question_type
                target_cat = chapter_category.get(ch)

                for paper in papers:
                    # 该卷内同题型题目，按"是否同学科 + 该题所属章节在卷内出现次数"排序，
                    # 优先换掉同学科且章节重复(>=2)的冗余题，避免破坏其它章节的唯一覆盖。
                    same_type = [q for q in paper.questions if q.question_type == qtype]
                    if not same_type:
                        continue
                    ch_count = Counter(q.chapter for q in same_type)

                    def victim_rank(q: QuestionItem) -> tuple[int, int, int]:
                        same_cat = 0 if (target_cat is None or q.category == target_cat) else 1
                        redundant = 0 if ch_count[q.chapter] >= 2 else 1
                        return (redundant, same_cat, ch_count[q.chapter] * -1)

                    victims = sorted(same_type, key=victim_rank)
                    # 只接受"移除后该章节仍被覆盖"的冗余victim，保证净覆盖 +1
                    victim = next((v for v in victims if ch_count[v.chapter] >= 2), None)
                    if victim is None:
                        continue

                    # 执行换入换出
                    v_idx = paper.questions.index(victim)
                    paper.questions[v_idx] = incoming
                    globally_selected_ids.discard(victim.id)
                    globally_selected_ids.add(incoming.id)
                    globally_covered_chapters.add(ch)

                    # 重排该卷，维持 章节序号 -> 难度 -> 题号 的稳定顺序
                    paper.questions.sort(key=lambda q: (
                        parse_chapter_number(q.chapter, q.id),
                        (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED).index(q.difficulty)
                        if q.difficulty in (DifficultyLevel.BASIC, DifficultyLevel.COMPREHENSIVE, DifficultyLevel.ADVANCED) else 1,
                        parse_qid_tuple(q.id),
                    ))
                    swapped = True
                    break
                if swapped:
                    break

    def _resolve_type_counts(self, mode: PaperMode, custom_counts: dict[QuestionType, int]) -> dict[QuestionType, int]:
        if mode in (PaperMode.FULL_10_6_6, PaperMode.BUNDLE_3_PAPERS):
            return {
                QuestionType.CHOICE: 10,
                QuestionType.FILL_BLANK: 6,
                QuestionType.SOLUTION: 6,
            }
        elif mode == PaperMode.SPRINT_5_3_3:
            return {
                QuestionType.CHOICE: 5,
                QuestionType.FILL_BLANK: 3,
                QuestionType.SOLUTION: 3,
            }
        elif mode == PaperMode.WRONG_NOTEBOOK:
            return custom_counts or {
                QuestionType.CHOICE: 5,
                QuestionType.FILL_BLANK: 3,
                QuestionType.SOLUTION: 2,
            }
        else:
            return {
                QuestionType.CHOICE: max(0, custom_counts.get(QuestionType.CHOICE, 10)),
                QuestionType.FILL_BLANK: max(0, custom_counts.get(QuestionType.FILL_BLANK, 6)),
                QuestionType.SOLUTION: max(0, custom_counts.get(QuestionType.SOLUTION, 6)),
            }

    def _filter_pool(
        self,
        source_questions: list[QuestionItem],
        target_chapters: set[str],
        tag_filter: str,
        difficulty_weights: dict[DifficultyLevel, float],
    ) -> list[QuestionItem]:
        filtered: list[QuestionItem] = []
        for q in source_questions:
            if target_chapters and q.chapter not in target_chapters:
                continue
            if tag_filter != "全部" and tag_filter not in q.tags:
                continue
            if difficulty_weights.get(q.difficulty, 1.0) <= 0.0:
                continue
            filtered.append(q)
        return filtered

    @staticmethod
    def _compute_score(
        question: QuestionItem,
        difficulty_weight: float,
        is_historically_uncovered: bool,
        current_chapter_count: int,
        seen_knowledge: Counter[str],
        chapter_weight: float = 1.0,
    ) -> float:
        base = max(0.1, float(question.recommend_weight))
        diff = max(0.01, difficulty_weight)
        chapter_boost = 3.5 if is_historically_uncovered else 1.0
        intra_penalty = 1.0 / (1.0 + 2.0 * current_chapter_count)
        chapter_pref = max(0.05, float(chapter_weight))  # 真题章节分布软权重

        if not question.core_knowledge:
            knowledge_factor = 1.0
        else:
            repeats = sum(seen_knowledge[k] for k in question.core_knowledge)
            unseen = sum(1 for k in question.core_knowledge if seen_knowledge[k] == 0)
            knowledge_factor = (1.0 + 1.5 * (unseen / len(question.core_knowledge))) / (1.0 + 0.8 * repeats)

        score = base * diff * chapter_boost * intra_penalty * knowledge_factor * chapter_pref
        return max(1e-6, score)

    @staticmethod
    def _roulette_select(scores: list[float], rng: random.Random) -> int:
        total = math.fsum(scores)
        if total <= 0:
            return rng.randrange(len(scores))
        threshold = rng.random() * total
        acc = 0.0
        for idx, s in enumerate(scores):
            acc += s
            if acc >= threshold:
                return idx
        return len(scores) - 1

    def _pick_from_pool(
        self,
        pool: list[QuestionItem],
        needed: int,
        request: "EngineRequest",
        unseen_chapters: set[str],
        chapter_usage: Counter,
        covered_knowledge: Counter,
        selected_ids: set[str],
        rng: random.Random,
    ) -> list[QuestionItem]:
        """从 pool 里按打分轮盘抽 needed 道（不重复），并更新章节/知识点计数。"""
        work = [q for q in pool if q.id not in selected_ids]
        chosen: list[QuestionItem] = []
        for _ in range(min(needed, len(work))):
            if not work:
                break
            scores = [
                self._compute_score(
                    question=q,
                    difficulty_weight=request.difficulty_weights.get(q.difficulty, 1.0),
                    is_historically_uncovered=q.chapter in unseen_chapters,
                    current_chapter_count=chapter_usage[q.chapter],
                    seen_knowledge=covered_knowledge,
                    chapter_weight=request.chapter_weights.get(
                        q.question_type.value, {}).get(q.chapter, 1.0),
                )
                for q in work
            ]
            idx = self._roulette_select(scores, rng)
            q = work.pop(idx)
            chosen.append(q)
            selected_ids.add(q.id)
            chapter_usage[q.chapter] += 1
            covered_knowledge.update(q.core_knowledge)
        return chosen

    def _pick_priority_then_fill(
        self,
        cat_pool: list[QuestionItem],
        needed: int,
        request: "EngineRequest",
        unseen_chapters: set[str],
        chapter_usage: Counter,
        covered_knowledge: Counter,
        selected_ids: set[str],
        rng: random.Random,
    ) -> list[QuestionItem]:
        """错题占比抽题：先从错题子集抽 round(needed*ratio)，其余用新题补；
        任一侧不足由另一侧自动补齐。ratio<=0 或无错题 → 全部普通抽。
        """
        ratio = max(0.0, min(1.0, request.priority_ratio))
        pri_ids = request.priority_pool_ids
        # seen 排除仅作用于"新题"；错题优先池永不排除(错题必须能重练)。
        seen = request.historical_seen_question_ids if request.exclude_seen else set()

        def _drop_seen(pool: list[QuestionItem]) -> list[QuestionItem]:
            """从新题池剔除已抽过的题；剔完为空则软重置(回退完整池)。"""
            if not seen:
                return pool
            filtered = [q for q in pool if q.id not in seen]
            return filtered if filtered else pool

        if ratio <= 0.0 or not pri_ids:
            # 全部普通抽 → 整个 cat_pool 都是"新题",按 seen 过滤 + 软重置
            new_only = _drop_seen(cat_pool)
            chosen = self._pick_from_pool(new_only, needed, request, unseen_chapters, chapter_usage, covered_knowledge, selected_ids, rng)
            # 过滤后抽不满(未见题不够) → 从完整池软重置补齐
            remaining = needed - len(chosen)
            if remaining > 0 and seen:
                chosen += self._pick_from_pool(cat_pool, remaining, request, unseen_chapters, chapter_usage, covered_knowledge, selected_ids, rng)
            return chosen

        want_pri = int(round(needed * ratio))
        pri_pool = [q for q in cat_pool if q.id in pri_ids]
        new_pool_full = [q for q in cat_pool if q.id not in pri_ids]
        new_pool = _drop_seen(new_pool_full)  # 新题池按 seen 过滤 + 软重置

        chosen: list[QuestionItem] = []
        chosen += self._pick_from_pool(pri_pool, want_pri, request, unseen_chapters, chapter_usage, covered_knowledge, selected_ids, rng)
        # 剩余名额（含错题不足时的缺口）用新题补
        remaining = needed - len(chosen)
        chosen += self._pick_from_pool(new_pool, remaining, request, unseen_chapters, chapter_usage, covered_knowledge, selected_ids, rng)
        # 未见新题不够 → 从完整新题池软重置补齐(允许已抽过的新题)
        remaining = needed - len(chosen)
        if remaining > 0 and seen:
            chosen += self._pick_from_pool(new_pool_full, remaining, request, unseen_chapters, chapter_usage, covered_knowledge, selected_ids, rng)
        # 新题仍不够 → 回补错题(原有兜底)
        remaining = needed - len(chosen)
        if remaining > 0:
            chosen += self._pick_from_pool(pri_pool, remaining, request, unseen_chapters, chapter_usage, covered_knowledge, selected_ids, rng)
        return chosen
