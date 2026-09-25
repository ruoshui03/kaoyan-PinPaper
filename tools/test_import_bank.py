"""
题库导入器回归测试（可直接 python 运行，也可被 pytest 收集）。

    python tools/test_import_bank.py
    python -m pytest tools/test_import_bank.py -q

锁住：CSV 列名映射 → 题型/难度兜底 → 落盘 → 注册清单 → 引擎可加载。
全部在 tmp 目录内完成，不污染仓库题库。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.bank_registry import load_books  # noqa: E402
from tools.import_bank import (  # noqa: E402
    normalize, read_csv, register_book, write_bank,
)

# 用 csv 模块生成，避免手工数逗号（题干里的半角逗号必须被引号包住，否则列错位）
CSV_ROWS = [
    {"题号": "T001", "题干": "设 $f(x)=x^2$，则 $f'(1)=$（　）",
     "A": "0", "B": "1", "C": "2", "D": "3", "答案": "C", "解析": "求导得 2x。",
     "章节": "第一章 函数、极限、连续", "题型": "选择题", "难度": "基础", "标签": "高频经典"},
    {"题号": "T002", "题干": "$\\int_0^1 x dx=$____",
     "A": "", "B": "", "C": "", "D": "", "答案": "1/2", "解析": "牛顿-莱布尼茨公式。",
     "章节": "第三章 一元函数积分学及其应用", "题型": "填空题", "难度": "基础", "标签": "计算量大"},
    {"题号": "T003", "题干": "证明 $\\sin x$ 在 [0,1] 上单调递增。",
     "A": "", "B": "", "C": "", "D": "", "答案": "", "解析": "由导数 cos x>0 即得。",
     "章节": "第二章 一元函数微分学及其应用", "题型": "解答题", "难度": "综合", "标签": "易错概念"},
]


def _write_csv(path: Path) -> None:
    import csv as _csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=list(CSV_ROWS[0].keys()))
        w.writeheader()
        w.writerows(CSV_ROWS)


def test_csv_to_items(tmp_path=None):
    base = Path(tmp_path) if tmp_path else Path(__file__).resolve().parent / "_tmp"
    base.mkdir(parents=True, exist_ok=True)
    csv_path = base / "sample.csv"
    _write_csv(csv_path)

    items = normalize(read_csv(csv_path))
    assert len(items) == 3, f"应解析出 3 题，实际 {len(items)}"
    by_id = {i["id"]: i for i in items}
    assert set(by_id) == {"T001", "T002", "T003"}

    assert by_id["T001"]["question_type"] == "选择题"
    assert len(by_id["T001"]["options"]) == 4, "选择题必须有 4 个选项"
    assert by_id["T001"]["answer"] == "C"
    assert by_id["T001"]["chapter"] == "第一章 函数、极限、连续"
    assert by_id["T001"]["difficulty"] == "基础题"

    assert by_id["T002"]["question_type"] == "填空题"
    assert by_id["T002"]["options"] == []
    assert by_id["T002"]["answer"] == "1/2"

    assert by_id["T003"]["question_type"] == "解答题"
    assert by_id["T003"]["difficulty"] == "综合题"

    # 落盘
    out = base / "bank_out"
    res = write_bank(items, "测试书", "数学一", out)
    assert res["items"] == 3 and res["chapters"] == 3
    meta = list((out / "metadata").glob("*.json"))
    assert len(meta) == 3, "按章节分文件，应有 3 个 metadata"
    payload = json.loads(meta[0].read_text(encoding="utf-8"))
    assert payload[0]["book"] == "测试书"
    assert (out / "problems").glob("*.md"), "应生成人读版 md"

    # 注册清单：order 必须排在内置三本之后（旧 URL 位图红线）
    order = register_book("测试书", "测试题库", "数学一", "bank_out", root=base)
    assert order > max(s.order for s in load_books(base)
                       if s.key in ("880", "真题", "张宇1000题")), \
        "新书 order 必须大于内置三本，否则旧链接失效"


def test_bank_is_loadable_by_engine(tmp_path=None):
    """落盘后的包必须能被 BankLoader 直接读出来。"""
    import shutil
    from core.bank_loader import BankLoader
    from core.models import SubjectType

    base = Path(tmp_path) if tmp_path else Path(__file__).resolve().parent / "_tmp2"
    if base.exists():
        shutil.rmtree(base)
    (base / "题库资料").mkdir(parents=True)
    csv_path = base / "s.csv"
    _write_csv(csv_path)

    items = normalize(read_csv(csv_path))
    write_bank(items, "引擎测试", "数学一", base / "题库资料" / "引擎测试数学一")
    register_book("引擎测试", "引擎测试题库", "数学一", "引擎测试数学一", root=base)

    loader = BankLoader(subject=SubjectType.MATH_1)
    # 让 loader 指向临时根（题库根目录探测基于 core/ 上级，这里直接换根）
    loader._root = base
    loader._books = load_books(base)
    questions = loader.load()
    mine = [q for q in questions if q.book == "引擎测试"]
    assert len(mine) == 3, f"引擎应读到 3 题，实际 {len(mine)}"
    assert {q.question_type.value for q in mine} == {"选择题", "填空题", "解答题"}


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_csv_to_items(Path(td) / "a")
        test_bank_is_loadable_by_engine(Path(td) / "b")
    print("题库导入器测试全部通过")
