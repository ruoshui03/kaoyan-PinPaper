"""
题库注册中心 (Bank Registry) —— 让"加一本新题库"变成放文件 + 写一行 JSON，不再改代码。

职责：
1. 书目清单 (manifest)：题库资料/books.json 声明有哪些书、每本书各科目在哪个目录、
   用什么布局解析。缺省回退到内置的三本（880 / 真题 / 1000题），行为与旧版完全一致。
2. 答案包 (answer pack)：solutions/<book_key>/ 或 题库资料/<目录>/answers/ 下的
   .json / .csv / .md 答案与解析，按题号回填进 QuestionItem。
3. 章节别名表：题库资料/章节别名表.json 把各书自带章节名归一到考纲章名。

兼容性红线：新增/改名只影响 appended 的书，内置三本书的加载顺序与题号保持不变，
因此 URL 位图（canonical_ids）不失效，用户收藏的老链接依旧可用。
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.models import SubjectType

MANIFEST_NAME = "books.json"
ALIAS_NAME = "章节别名表.json"
ANSWER_DIR_NAME = "answers"
CENTRAL_SOLUTION_DIR = "solutions"

SUBJECT_ORDER = (SubjectType.MATH_1, SubjectType.MATH_2, SubjectType.MATH_3)


# --------------------------------------------------------------------------
# 内置书目（manifest 缺失时的默认值，与旧硬编码行为一致）
# --------------------------------------------------------------------------
def _default_books() -> list[dict[str, Any]]:
    def dirs_of(base: str) -> dict[str, str]:
        return {s.value: f"{base}{s.value}" for s in SUBJECT_ORDER}

    return [
        {"key": "880", "name": "李林《880》", "order": 1, "layout": "880",
         "dirs": {"数学一": "880数学一", "数学二": "880数学二", "数学三": "880数学三"}},
        {"key": "真题", "name": "历年真题 2010–2026", "order": 2, "layout": "self_contained",
         "dirs": {"数学一": "真题数学一", "数学二": "真题数学二", "数学三": "真题数学三"}},
        {"key": "张宇1000题", "name": "张宇《1000题》", "order": 3, "layout": "self_contained",
         "dirs": {"数学一": "1000题数学一", "数学二": "1000题数学二", "数学三": "1000题数学三"}},
    ]


@dataclass
class BookSpec:
    """一本书的声明。layout=880 走题面/元数据对齐+重编号；self_contained 走自包含直读。"""
    key: str
    name: str
    order: int
    layout: str
    dirs: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    subjects: list[str] = field(default_factory=lambda: [s.value for s in SUBJECT_ORDER])
    raw: dict[str, Any] = field(default_factory=dict)

    def dir_for(self, subject: SubjectType) -> str | None:
        return self.dirs.get(subject.value)


def bank_root() -> Path:
    """题库根目录：优先 core/ 的上级（仓库根），否则当前工作目录。"""
    here = Path(__file__).resolve().parent.parent
    return here if (here / "题库资料").exists() else Path.cwd()


def load_books(root: Path | str | None = None) -> list[BookSpec]:
    """读取书目清单。manifest 里的条目覆盖同名内置条目，未声明的内置书自动补上。"""
    root = Path(root) if root else bank_root()
    raw_list: list[dict[str, Any]] = []
    mf = root / "题库资料" / MANIFEST_NAME
    if mf.exists():
        try:
            payload = json.loads(mf.read_text(encoding="utf-8-sig"))
            raw_list = list(payload.get("books", payload if isinstance(payload, list) else []))
        except Exception:
            raw_list = []

    merged: dict[str, dict[str, Any]] = {b["key"]: dict(b) for b in _default_books()}
    for b in raw_list:
        if not isinstance(b, dict) or not b.get("key"):
            continue
        key = str(b["key"])
        merged[key] = {**merged.get(key, {}), **b}

    specs: list[BookSpec] = []
    for key, b in merged.items():
        dirs = {str(k): str(v) for k, v in (b.get("dirs") or {}).items()}
        specs.append(BookSpec(
            key=key,
            name=str(b.get("name") or key),
            order=int(b.get("order") or 999),
            layout=str(b.get("layout") or "self_contained"),
            dirs=dirs,
            enabled=bool(b.get("enabled", True)),
            subjects=[str(s) for s in (b.get("subjects") or [s.value for s in SUBJECT_ORDER])],
            raw=b,
        ))
    specs.sort(key=lambda s: (s.order, s.key))
    return specs


def save_books(specs: Iterable[BookSpec], root: Path | str | None = None) -> Path:
    """写回书目清单（导入器用）。"""
    root = Path(root) if root else bank_root()
    mf = root / "题库资料" / MANIFEST_NAME
    payload = {
        "version": 1,
        "note": "书目清单。新增题库：把目录放进 题库资料/，在此处加一条 dirs 声明即可，无需改代码。",
        "books": [
            {"key": s.key, "name": s.name, "order": s.order, "layout": s.layout,
             "enabled": s.enabled, "subjects": s.subjects, "dirs": s.dirs}
            for s in specs
        ],
    }
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return mf


# --------------------------------------------------------------------------
# 答案 / 解析包
# --------------------------------------------------------------------------
def answer_dirs_for(book: BookSpec, subject: SubjectType, root: Path | str | None = None) -> list[Path]:
    """答案包搜索路径（按优先级从低到高）：书内 answers/ → 集中 solutions/<key>/<科目>/"""
    root = Path(root) if root else bank_root()
    out: list[Path] = []
    d = book.dir_for(subject)
    if d:
        out.append(root / "题库资料" / d / ANSWER_DIR_NAME)
    out.append(root / CENTRAL_SOLUTION_DIR / book.key / subject.value)
    out.append(root / CENTRAL_SOLUTION_DIR / book.key)
    return out


def _parse_json_pack(text: str) -> list[dict[str, str]]:
    data = json.loads(text)
    rows = data.get("items", data) if isinstance(data, dict) else data
    out: list[dict[str, str]] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        qid = str(r.get("id") or r.get("qid") or "").strip()
        if qid:
            out.append({"id": qid, "answer": str(r.get("answer") or "").strip(),
                        "solution": str(r.get("solution") or r.get("解析") or "").strip()})
    return out


def _parse_csv_pack(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, str]] = []
    for row in reader:
        qid = str(row.get("id") or row.get("题号") or row.get("qid") or "").strip()
        if not qid:
            continue
        out.append({"id": qid,
                    "answer": str(row.get("answer") or row.get("答案") or "").strip(),
                    "solution": str(row.get("solution") or row.get("解析") or "").strip()})
    return out


_MD_HEAD = re.compile(r"^#{1,6}\s*\*{0,2}(?P<id>[A-Za-z0-9\u4e00-\u9fa5_\-]+)\*{0,2}\s*$")
_ANS_LINE = re.compile(r"^【答案】\s*(?P<a>.+)$")


def _parse_md_pack(text: str) -> list[dict[str, str]]:
    """Markdown 答案包：

    ## 01-基础-选-01
    【答案】C
    【解析】先对方程两端求导……
    """
    out: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    sol_lines: list[str] = []
    in_sol = False
    for line in text.splitlines():
        m = _MD_HEAD.match(line.strip())
        if m:
            if cur:
                cur["solution"] = "\n".join(sol_lines).strip()
                out.append(cur)
            cur = {"id": m.group("id").strip(), "answer": "", "solution": ""}
            sol_lines, in_sol = [], False
            continue
        if cur is None:
            continue
        t = line.strip()
        if t.startswith("【答案】"):
            cur["answer"] = (_ANS_LINE.match(t).group("a") if _ANS_LINE.match(t) else "").strip()
            in_sol = False
        elif t.startswith("【解析】"):
            in_sol = True
            sol_lines.append(t[len("【解析】"):].strip())
        elif in_sol:
            sol_lines.append(t)
    if cur:
        cur["solution"] = "\n".join(sol_lines).strip()
        out.append(cur)
    return out


def load_answer_pack(
    book: BookSpec,
    subject: SubjectType,
    root: Path | str | None = None,
) -> dict[str, dict[str, str]]:
    """汇总该书该科目的全部答案包 → {题号: {"answer":..., "solution":...}}。"""
    pack: dict[str, dict[str, str]] = {}
    for d in answer_dirs_for(book, subject, root):
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (".json", ".csv", ".md", ".txt"):
                continue
            try:
                text = f.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            rows: list[dict[str, str]] = []
            try:
                if f.suffix.lower() == ".json":
                    rows = _parse_json_pack(text)
                elif f.suffix.lower() == ".csv":
                    rows = _parse_csv_pack(text)
                else:
                    rows = _parse_md_pack(text)
            except Exception:
                continue
            for r in rows:
                if r["answer"] or r["solution"]:
                    prev = pack.get(r["id"], {})
                    pack[r["id"]] = {
                        "answer": r["answer"] or prev.get("answer", ""),
                        "solution": r["solution"] or prev.get("solution", ""),
                    }
    return pack


# --------------------------------------------------------------------------
# 章节别名表
# --------------------------------------------------------------------------
def load_chapter_aliases(
    subject: SubjectType,
    root: Path | str | None = None,
) -> dict[str, str]:
    """{原章节名: 考纲章节名}。表缺失 → 空 dict（特性静默不启用，与旧行为一致）。"""
    root = Path(root) if root else bank_root()
    f = root / "题库资料" / ALIAS_NAME
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    block = data.get(subject.value, data.get("default", {})) if isinstance(data, dict) else {}
    if not isinstance(block, dict):
        return {}
    return {str(k): str(v) for k, v in block.items()}
