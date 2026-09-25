"""
本机题库导入器：把你自己手上的题库文件（JSON / CSV / Markdown，文件或整个目录）
转成项目标准包，并可选自动注册进 题库资料/books.json。

用法：
    # 先看会解析出什么（不落盘）
    python tools/import_bank.py --from ./我的题库.csv --book-key 660 --subject 数学一 --dry-run

    # 正式导入：生成 题库资料/660数学一/{metadata,problems} 并注册进清单
    python tools/import_bank.py --from ./我的题库.csv --book-key 660 --name "李永乐660" \
        --subject 数学一 --dir 660数学一 --register

    # 整个目录（递归合并所有 json/csv/md）
    python tools/import_bank.py --from ./题库文件夹 --book-key 自编 --subject 数学二 --register

支持的输入列名（大小写/中英文都认）：
    id/题号/编号 | stem/题干/题目/Question | A/B/C/D 或 options/选项
    answer/答案 | solution/解析 | chapter/章节 | type/题型 | difficulty/难度 | tags/标签
章节缺失会给"未分类章节"，题型/难度缺失按关键词兜底判定，题号缺失自动生成。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.bank_registry import (  # noqa: E402
    BookSpec, bank_root, load_books, save_books,
)
from core.models import SubjectType  # noqa: E402

# 列名同义词 → 标准字段
FIELD_ALIASES = {
    "id": ["id", "题号", "编号", "qid", "question_id", "no"],
    "stem": ["stem", "题干", "题目", "question", "content", "body", "text"],
    "answer": ["answer", "答案", "参考答案", "ans"],
    "solution": ["solution", "解析", "详解", "解答", "analysis", "explain"],
    "chapter": ["chapter", "章节", "章", "所属章节", "section"],
    "type": ["type", "题型", "question_type", "qtype"],
    "difficulty": ["difficulty", "难度", "level", "难度等级"],
    "tags": ["tags", "标签", "考点", "tag"],
    "options": ["options", "选项", "choices"],
}
OPT_COLS = ["A", "B", "C", "D"]

TYPE_MAP = {"选择题": "选择题", "单选": "选择题", "选择": "选择题",
            "填空题": "填空题", "填空": "填空题",
            "解答题": "解答题", "计算": "解答题", "证明": "解答题", "大题": "解答题"}
DIFF_MAP = {"基础": "基础题", "简单": "基础题", "综合": "综合题", "中等": "综合题",
            "拓展": "拓展题", "拔高": "拓展题", "困难": "拓展题"}


def _norm_key(k: str) -> str:
    return re.sub(r"[\s_\-()（）]", "", str(k or "")).lower()


def _map_columns(keys: list[str]) -> dict[str, str]:
    """把实际列名映射到标准字段（返回 {标准字段: 实际列名}）。"""
    out: dict[str, str] = {}
    lowered = {_norm_key(k): k for k in keys}
    for std, aliases in FIELD_ALIASES.items():
        for a in aliases:
            if _norm_key(a) in lowered:
                out[std] = lowered[_norm_key(a)]
                break
    return out


def _guess_type_ex(row: dict, options: list[str]) -> tuple[str, bool]:
    """判定题型，第二个返回值表示「是否靠内容推测」（True 建议人工核对）。

    CSV 里题干若含半角逗号又没加引号，列会整体错位 —— 这种错误不会报错，
    只会静默产出垃圾数据。故把「题型是推测出来的」这类可疑条目统计出来提示用户。
    """
    raw = str(row.get("type") or "")
    for k, v in TYPE_MAP.items():
        if k in raw:
            return v, False
    if options:
        return "选择题", True
    stem = str(row.get("stem") or "")
    if re.search(r"（\s*）|\(\s*\)|____|______", stem):
        return "填空题", True
    return "解答题", True


def _guess_type(row: dict, options: list[str]) -> str:
    return _guess_type_ex(row, options)[0]


def _guess_difficulty(row: dict) -> str:
    raw = str(row.get("difficulty") or "")
    for k, v in DIFF_MAP.items():
        if k in raw:
            return v
    return "综合题"


def _parse_tags(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    s = str(raw or "").strip()
    if not s:
        return []
    return [t.strip() for t in re.split(r"[,，;；/|、]", s) if t.strip()]


def _row_to_item(row: dict, colmap: dict[str, str], seq: int) -> dict | None:
    get = lambda f: str(row.get(colmap.get(f, ""), "") or "").strip()  # noqa: E731
    # CSV 里列名就是标准字段时（自己手写的极简表）直接取值
    def val(f: str) -> str:
        c = colmap.get(f)
        if c and c in row:
            return str(row[c] or "").strip()
        return str(row.get(f) or "").strip()

    stem = val("stem")
    if not stem:
        return None

    options: list[str] = []
    raw_opts = val("options")
    if raw_opts:
        try:
            parsed = json.loads(raw_opts)
            if isinstance(parsed, list):
                options = [str(o).strip() for o in parsed if str(o).strip()]
        except Exception:
            options = [s.strip() for s in re.split(r"[;\n]", raw_opts) if s.strip()]
    if not options:
        for letter in OPT_COLS:
            v = str(row.get(letter) or row.get(f"选项{letter}") or "").strip()
            if v:
                options.append(f"{letter}. {v}")
    if not options:
        # 题干里自带的 A. … B. …（单行挤在一起的情况）
        m = re.search(r"A\s*[.．、]\s*.+B\s*[.．、]\s*.+", stem)
        if m:
            parts = re.split(r"(?=(?:A|B|C|D)\s*[.．、]\s*)", stem[m.start():])
            options = [p.strip() for p in parts if p.strip()]
            stem = stem[:m.start()].strip()

    qid = val("id") or f"{seq:04d}"
    chapter = val("chapter") or "未分类章节"
    qtype, guessed = _guess_type_ex({"type": val("type")}, options)
    return {
        "id": qid,
        "book": "",  # 由调用方统一填
        "chapter": chapter,
        "question_type": qtype,
        "_guessed_type": guessed,
        "difficulty": _guess_difficulty({"difficulty": val("difficulty")}),
        "tags": _parse_tags(val("tags") or row.get(colmap.get("tags", ""))),
        "stem": stem,
        "options": options,
        "answer": val("answer"),
        "solution": val("solution"),
    }


# --------------------------------------------------------------------------
# 各格式读取
# --------------------------------------------------------------------------
def read_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = data.get("items", data) if isinstance(data, dict) else data
    return [r for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict)]


def read_csv(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]


def read_md(path: Path) -> list[dict]:
    """Markdown：## 题号 分段；【答案】/【解析】行；A. B. C. D. 行作为选项。"""
    items: list[dict] = []
    cur: dict | None = None
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        t = line.strip()
        if re.match(r"^#{1,6}\s+\S", t):
            if cur:
                cur["stem"] = "\n".join(lines).strip()
                items.append(cur)
            cur = {"id": re.sub(r"^#{1,6}\s+", "", t).strip(), "chapter": "未分类章节",
                   "options": [], "answer": "", "solution": "", "tags": [], "stem": ""}
            lines = []
            continue
        if cur is None:
            continue
        if t.startswith("【答案】"):
            cur["answer"] = t[len("【答案】"):].strip()
        elif t.startswith("【解析】"):
            cur["solution"] = t[len("【解析】"):].strip()
        elif re.match(r"^[A-D]\s*[.．、]\s*\S", t):
            cur["options"].append(t)
        elif t:
            lines.append(t)
    if cur:
        cur["stem"] = "\n".join(lines).strip()
        items.append(cur)
    for it in items:
        it.setdefault("chapter", "未分类章节")
        it["question_type"] = _guess_type({}, it["options"])
        it["difficulty"] = "综合题"
    return items


def load_source(src: Path) -> list[dict]:
    if src.is_dir():
        rows: list[dict] = []
        for f in sorted(src.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".json", ".csv", ".md", ".txt"):
                rows += (read_json(f) if f.suffix.lower() == ".json"
                         else read_csv(f) if f.suffix.lower() == ".csv"
                         else read_md(f))
        return rows
    if src.suffix.lower() == ".json":
        return read_json(src)
    if src.suffix.lower() == ".csv":
        return read_csv(src)
    return read_md(src)


def normalize(rows: list[dict]) -> list[dict]:
    """把任意来源的行归一成标准 item（含列映射、题型/难度兜底、题号补全）。"""
    if not rows:
        return []
    colmap = _map_columns(list(rows[0].keys()))
    items: list[dict] = []
    for i, row in enumerate(rows, 1):
        if "stem" in row and "options" in row and "question_type" in row and "difficulty" in row and "id" in row:
            it = dict(row)            # 已是标准结构（JSON 直供）
            it.setdefault("chapter", "未分类章节")
            it.setdefault("answer", "")
            it.setdefault("solution", "")
            it.setdefault("tags", [])
            it.setdefault("options", [])
        else:
            it = _row_to_item(row, colmap, i)
        if it:
            items.append(it)
    # 题号去重与补全
    used: set[str] = set()
    for idx, it in enumerate(items, 1):
        qid = str(it.get("id") or "").strip()
        if not qid or qid in used:
            qid = f"{idx:04d}"
            while qid in used:
                idx += 1
                qid = f"{idx:04d}"
        it["id"] = qid
        used.add(qid)
    return items


def write_bank(items: list[dict], book_key: str, subject: str, out_dir: Path,
               write_md: bool = True) -> dict:
    """落盘成 题库资料/<dir>/{metadata,problems}。按章节分文件。"""
    for it in items:
        it["book"] = book_key
        it.pop("_guessed_type", None)
    meta_dir = out_dir / "metadata"
    prob_dir = out_dir / "problems"
    meta_dir.mkdir(parents=True, exist_ok=True)
    prob_dir.mkdir(parents=True, exist_ok=True)

    by_ch: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_ch[it["chapter"]].append(it)

    for ch, group in by_ch.items():
        safe = re.sub(r"[\\/:*?\"<>|]", "_", ch)[:60] or "未分类章节"
        (meta_dir / f"{safe}.json").write_text(
            json.dumps(group, ensure_ascii=False, indent=2), encoding="utf-8")
        if write_md:
            md = [f"# {ch}", ""]
            for it in group:
                md.append(f"## {it['id']}")
                md.append(it["stem"])
                md.append("")
                for o in it["options"]:
                    md.append(o)
                if it["options"]:
                    md.append("")
                if it["answer"]:
                    md.append(f"【答案】{it['answer']}")
                if it["solution"]:
                    md.append(f"【解析】{it['solution']}")
                md.append("")
            (prob_dir / f"{safe}.md").write_text("\n".join(md), encoding="utf-8")
    return {"dir": str(out_dir), "chapters": len(by_ch), "items": len(items)}


def register_book(book_key: str, name: str, subject: str, dir_name: str,
                  root: Path | None = None) -> int:
    """写入 books.json。order 取现有最大值 +1（保证排在内置三本之后，旧 URL 不失效）。"""
    root = root or bank_root()
    specs = load_books(root)
    order = max([s.order for s in specs] + [9]) + 1
    existing = next((s for s in specs if s.key == book_key), None)
    if existing:
        existing.dirs[subject] = dir_name
        existing.name = name or existing.name
        existing.enabled = True
    else:
        specs.append(BookSpec(key=book_key, name=name or book_key, order=order,
                              layout="self_contained", dirs={subject: dir_name},
                              enabled=True))
    save_books(specs, root)
    return order


def main() -> int:
    ap = argparse.ArgumentParser(description="本机题库导入器")
    ap.add_argument("--from", dest="src", required=True, help="文件或目录")
    ap.add_argument("--book-key", required=True, help="内部 key，如 660")
    ap.add_argument("--name", default="", help="显示名")
    ap.add_argument("--subject", required=True, choices=["数学一", "数学二", "数学三"])
    ap.add_argument("--dir", dest="dir_name", default="", help="输出目录名，默认 <key><科目>")
    ap.add_argument("--register", action="store_true", help="写入 books.json")
    ap.add_argument("--no-md", action="store_true", help="不生成人读版 md")
    ap.add_argument("--dry-run", action="store_true", help="只报告不落盘")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"找不到 {src}")
        return 1
    root = bank_root()
    dir_name = args.dir_name or f"{args.book_key}{args.subject}"
    out_dir = root / "题库资料" / dir_name

    rows = load_source(src)
    items = normalize(rows)
    if not items:
        print("没有解析出任何题目，检查文件格式或列名（支持 id/stem/options/A-D/answer/solution/chapter/type/difficulty/tags）")
        return 1

    types = Counter(i["question_type"] for i in items)
    chs = Counter(i["chapter"] for i in items)
    no_ans = sum(1 for i in items if not i["answer"])
    print(f"解析 {len(items)} 题 | 题型 {dict(types)} | 章节 {len(chs)} 个 | 无答案 {no_ans}")
    for ch, n in list(chs.most_common(5)):
        print(f"  {ch}: {n} 题")
    guessed = [i["id"] for i in items if i.get("_guessed_type")]
    if guessed:
        print(f"⚠ 题型靠内容推测（原表题型列缺失/可疑）：{len(guessed)} 例 → {guessed[:5]}")
        print("  CSV 题干里若有半角逗号必须加英文双引号，否则整行列会错位。")
    bad = [i["id"] for i in items if i["question_type"] == "选择题" and len(i["options"]) != 4]
    if bad:
        print(f"⚠ 选择题选项数不为 4：{len(bad)} 例 → {bad[:5]}")
    dup = [k for k, v in Counter(i["id"] for i in items).items() if v > 1]
    if dup:
        print(f"⚠ 题号重复（已自动改写）：{dup[:5]}")

    if args.dry_run:
        print("（dry-run，未落盘）")
        return 0

    res = write_bank(items, args.book_key, args.subject, out_dir, write_md=not args.no_md)
    print(f"已写入 {res['dir']}：{res['items']} 题 / {res['chapters']} 章")

    if args.register:
        order = register_book(args.book_key, args.name, args.subject, dir_name, root)
        print(f"已注册进 题库资料/books.json（order={order}）")
        print("提示：order 排在内置三本之后，旧分享链接不会失效。")
    else:
        print("未注册。手动加清单或用 --register："
              f'在 题库资料/books.json 加 {{"key":"{args.book_key}","layout":"self_contained",'
              f'"dirs":{{"{args.subject}":"{dir_name}"}},"enabled":true}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
