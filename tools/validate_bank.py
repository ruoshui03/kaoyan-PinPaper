"""
题库体检：给出每题可核查的质量指标，供贡献者在提交前自查。

用法：
    python tools/validate_bank.py                      # 三科全量体检
    python tools/validate_bank.py --subject 数学一      # 只查一科
    python tools/validate_bank.py --json report.json   # 导出机器可读报告
    python tools/validate_bank.py --strict             # 有 ERROR 时以非零码退出（CI 用）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.bank_loader import BankLoader  # noqa: E402
from core.models import (  # noqa: E402
    MATH_1_CHAPTERS, MATH_2_CHAPTERS, MATH_3_CHAPTERS, SubjectType,
)

CHAPTERS = {
    SubjectType.MATH_1: MATH_1_CHAPTERS,
    SubjectType.MATH_2: MATH_2_CHAPTERS,
    SubjectType.MATH_3: MATH_3_CHAPTERS,
}
SUBSCRIPTIONS = {"数学一": SubjectType.MATH_1, "数学二": SubjectType.MATH_2, "数学三": SubjectType.MATH_3}


def check_subject(subject: SubjectType) -> dict:
    loader = BankLoader(subject=subject)
    questions = loader.load()

    stats = {
        "subject": subject.value,
        "total": len(questions),
        "by_book": {},
        "issues": defaultdict(list),
        "answer_coverage": 0.0,
        "solution_coverage": 0.0,
        "chapters": len(loader.chapters),
        "off_syllabus_chapters": [],
        "type_dist": dict(Counter(q.question_type.value for q in questions)),
        "difficulty_dist": dict(Counter(q.difficulty.value for q in questions)),
    }

    by_book: dict[str, list] = defaultdict(list)
    for q in questions:
        by_book[q.book].append(q)

    for book, items in sorted(by_book.items()):
        n = len(items)
        no_ans = [q.id for q in items if not q.answer.strip()]
        no_sol = [q.id for q in items if not q.solution.strip()]
        no_stem = [q.id for q in items if not q.stem.strip()]
        bad_opt = [q.id for q in items if q.question_type.value == "选择题" and len(q.options) != 4]
        no_opt = [q.id for q in items if q.question_type.value == "选择题" and not q.options]
        odd_dollar = [q.id for q in items if q.stem.replace("$$", "").count("$") % 2]
        broken_img = [q.id for q in items if "(图" in q.stem and "见原书" in q.stem]

        stats["by_book"][book] = {
            "count": n,
            "answer_missing": len(no_ans),
            "solution_missing": len(no_sol),
            "stem_empty": len(no_stem),
            "options_not_4": len(bad_opt),
            "options_empty": len(no_opt),
            "math_delim_broken": len(odd_dollar),
            "image_missing": len(broken_img),
            "type_dist": dict(Counter(q.question_type.value for q in items)),
        }

        if no_stem:
            stats["issues"][f"{book}/空题干"].extend(no_stem[:20])
        if bad_opt:
            stats["issues"][f"{book}/选择题选项数不为4"].extend(bad_opt[:20])
        if odd_dollar:
            stats["issues"][f"{book}/公式定界符$不成对"].extend(odd_dollar[:20])
        if broken_img:
            stats["issues"][f"{book}/图片缺失(退化为占位)"].extend(broken_img[:20])

    stats["answer_coverage"] = round(
        sum(1 for q in questions if q.answer.strip()) / max(1, len(questions)) * 100, 2)
    stats["solution_coverage"] = round(
        sum(1 for q in questions if q.solution.strip()) / max(1, len(questions)) * 100, 2)

    syllabus = set(CHAPTERS[subject])
    extra = [c for c in loader.chapters if c not in syllabus]
    stats["off_syllabus_chapters"] = extra

    # 跨书题号冲突（loader 会静默跳过后加载的同号题）
    seen: dict[str, str] = {}
    for q in questions:
        pass  # questions_by_id 已去重，冲突需在源数据层检查
    id_files: dict[str, set[str]] = defaultdict(set)
    root = Path(__file__).resolve().parent.parent / "题库资料"
    for jf in root.rglob("metadata/*.json"):
        try:
            data = json.loads(jf.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for it in (data if isinstance(data, list) else [data]):
            if isinstance(it, dict) and it.get("id"):
                id_files[str(it["id"])].add(str(jf.relative_to(root)))
    conflicts = {k: sorted(v) for k, v in id_files.items() if len(v) > 1}
    stats["id_conflicts_across_files"] = conflicts
    stats["issues"]["跨文件题号重复"] = sorted(conflicts.keys())[:20]

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="题库体检")
    ap.add_argument("--subject", choices=list(SUBSCRIPTIONS.keys()), default=None)
    ap.add_argument("--json", dest="json_out", default=None, help="导出 JSON 报告路径")
    ap.add_argument("--strict", action="store_true", help="存在 ERROR 时退出码 1")
    args = ap.parse_args()

    subjects = [SUBSCRIPTIONS[args.subject]] if args.subject else list(SUBSCRIPTIONS.values())
    reports = [check_subject(s) for s in subjects]

    for r in reports:
        print(f"\n===== {r['subject']}  共 {r['total']} 题 / {r['chapters']} 章 =====")
        print(f"  答案覆盖率 {r['answer_coverage']}%   解析覆盖率 {r['solution_coverage']}%")
        for book, b in r["by_book"].items():
            print(f"  [{book}] n={b['count']:<5} "
                  f"空答案={b['answer_missing']:<5} 空解析={b['solution_missing']:<5} "
                  f"空题干={b['stem_empty']} 选项≠4={b['options_not_4']} "
                  f"公式异常={b['math_delim_broken']} 缺图={b['image_missing']}")
        if r["off_syllabus_chapters"]:
            print("  非考纲章(建议补 章节别名表.json):", "、".join(r["off_syllabus_chapters"]))
        for name, ids in r["issues"].items():
            if ids:
                shown = "、".join(ids[:8]) + ("…" if len(ids) > 8 else "")
                print(f"  ⚠ {name}: {len(ids)} 例 → {shown}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 报告已写入 {args.json_out}")

    error = any(r["by_book"][b]["stem_empty"] or r["by_book"][b]["options_not_4"]
                or r["by_book"][b]["math_delim_broken"]
                for r in reports for b in r["by_book"])
    return 1 if (args.strict and error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
