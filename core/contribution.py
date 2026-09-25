"""
答案 / 解析的去中心化贡献中心（用户授权制，默认不外发任何数据）。

设计前提：题库素材版权归原作者，答案与解析由使用者自行产出。本模块只做三件事：
1. 把你本地填好的答案/解析打包成可分享的贡献包（.kpp.json），导出与否由你点授权；
2. 把别人分享给你的包（文件 / URL / IPFS CID / 你自己的 Git 仓库）导入本地；
3. 记录每条答案的来源与署名，本地可查覆盖率与贡献者分布。

红线：
- 不内置任何远程地址，不默认联网，不发遥测。任何 pull/push 必须由用户显式给出目标；
- 导入前校验题号是否真实存在于本地题库，垃圾/错位数据直接拒绝；
- 版权与授权声明随包携带，导入时展示给使用者。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from core.bank_registry import CENTRAL_SOLUTION_DIR, bank_root
from core.models import SubjectType

PACK_FORMAT = "kpp/1"
OUTBOX_DIR = "solutions/_outbox"
INBOX_DIR = "solutions/_inbox"
CONSENT_FILE = "solutions/consent.json"
DEFAULT_LICENSE = "CC BY-NC 4.0 · 仅供学习交流，题库素材版权归原作者"

SUBJECTS = (SubjectType.MATH_1, SubjectType.MATH_2, SubjectType.MATH_3)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def solutions_root(root: Path | str | None = None) -> Path:
    return (Path(root) if root else bank_root()) / CENTRAL_SOLUTION_DIR


def read_consent(root: Path | str | None = None) -> dict:
    """读取共享授权状态。默认全部关闭。"""
    f = (Path(root) if root else bank_root()) / CONSENT_FILE
    default = {"share": False, "attribution": True, "author": "", "updated_at": ""}
    if f.exists():
        try:
            return {**default, **json.loads(f.read_text(encoding="utf-8"))}
        except Exception:
            return default
    return default


def write_consent(share: bool, author: str = "", attribution: bool = True,
                  root: Path | str | None = None) -> Path:
    root = Path(root) if root else bank_root()
    f = root / CONSENT_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"share": bool(share), "attribution": bool(attribution),
                             "author": author, "updated_at": _now()},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return f


# --------------------------------------------------------------------------
# 贡献包读写
# --------------------------------------------------------------------------
def make_pack(book: str, subject: SubjectType | str, items: list[dict[str, Any]],
              author: str = "", license_: str = DEFAULT_LICENSE,
              share: bool = False, secret: str | None = None) -> dict:
    sub = subject.value if isinstance(subject, SubjectType) else str(subject)
    cleaned = []
    for it in items:
        qid = str(it.get("id") or "").strip()
        if not qid:
            continue
        ans = str(it.get("answer") or "").strip()
        sol = str(it.get("solution") or "").strip()
        if not ans and not sol:
            continue
        cleaned.append({"id": qid, "answer": ans, "solution": sol})
    pack: dict[str, Any] = {
        "format": PACK_FORMAT,
        "book": book,
        "subject": sub,
        "author": author,
        "license": license_,
        "consent": {"share": bool(share)},
        "created_at": _now(),
        "count": len(cleaned),
        "items": cleaned,
    }
    if secret:
        pack["signature"] = sign_pack(pack, secret)
    return pack


def sign_pack(pack: dict, secret: str) -> str:
    body = json.dumps(pack.get("items", []), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_pack(pack: dict, secret: str) -> bool:
    sig = pack.get("signature")
    if not sig:
        return False
    return hmac.compare_digest(sig, sign_pack(pack, secret))


def export_pack(book: str, subject: SubjectType | str, root: Path | str | None = None,
                author: str = "", share: bool = False, out_dir: str | None = None,
                secret: str | None = None) -> Path:
    """把本地 solutions/<book>/<subject>/ 下已有的答案打包导出到 outbox。"""
    root = Path(root) if root else bank_root()
    sub = subject.value if isinstance(subject, SubjectType) else str(subject)
    src_dir = solutions_root(root) / book / sub
    items = collect_local_items(book, sub, root)
    if not items:
        raise ValueError(f"没有可导出的答案：{src_dir} 为空")

    pack = make_pack(book, sub, items, author=author, share=share, secret=secret)
    target_dir = root / (out_dir or OUTBOX_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_book = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", book)
    out = target_dir / f"{safe_book}_{sub}_{datetime.now():%Y%m%d-%H%M%S}.kpp.json"
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def collect_local_items(book: str, subject: str, root: Path | str | None = None) -> list[dict]:
    """汇总本地 solutions/<book>/<subject>/ 下的全部条目（json/csv/md）。"""
    from core.bank_registry import _parse_csv_pack, _parse_json_pack, _parse_md_pack
    root = Path(root) if root else bank_root()
    d = solutions_root(root) / book / subject
    if not d.exists():
        return []
    out: dict[str, dict] = {}
    for f in sorted(d.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in (".json", ".csv", ".md", ".txt"):
            continue
        try:
            text = f.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        try:
            rows = (_parse_json_pack(text) if f.suffix.lower() == ".json"
                    else _parse_csv_pack(text) if f.suffix.lower() == ".csv"
                    else _parse_md_pack(text))
        except Exception:
            continue
        for r in rows:
            if r["id"] and (r["answer"] or r["solution"]):
                prev = out.get(r["id"], {})
                out[r["id"]] = {"id": r["id"],
                                "answer": r["answer"] or prev.get("answer", ""),
                                "solution": r["solution"] or prev.get("solution", "")}
    return list(out.values())


# --------------------------------------------------------------------------
# 导入
# --------------------------------------------------------------------------
def _load_pack_items(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        from core.bank_registry import _parse_csv_pack
        return _parse_csv_pack(text)
    if path.suffix.lower() in (".md", ".txt"):
        from core.bank_registry import _parse_md_pack
        return _parse_md_pack(text)
    data = json.loads(text)
    if isinstance(data, dict) and "items" in data:
        return [dict(i) for i in data["items"] if isinstance(i, dict)]
    if isinstance(data, list):
        return [dict(i) for i in data if isinstance(i, dict)]
    return []


def import_pack(
    source: str | Path,
    valid_ids: Iterable[str] | None = None,
    root: Path | str | None = None,
    strategy: str = "remote",   # remote=以导入为准 / local=保留本地 / longest=取更长的解析
    book_override: str | None = None,
    subject_override: str | None = None,
    secret: str | None = None,
) -> dict:
    """导入一个贡献包（本地路径 / URL / IPFS CID）到本地 solutions/。

    返回统计 dict：{total, accepted, unknown_ids, conflicts, written, author, license}
    """
    root = Path(root) if root else bank_root()
    path = Path(str(source))
    tmp: Path | None = None

    if str(source).startswith(("http://", "https://")):
        tmp = root / INBOX_DIR / "_download.kpp.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(str(source), timeout=60) as resp:  # noqa: S310 - 用户显式提供
            tmp.write_bytes(resp.read())
        path = tmp
    elif str(source).startswith(("ipfs://", "/ipfs/")) or re.fullmatch(r"Qm[1-9A-HJ-NP-Za-km-z]{44,}", str(source)):
        cid = str(source).split("/")[-1]
        if not shutil.which("ipfs"):
            raise RuntimeError("未检测到本机 ipfs 命令，无法按 CID 拉取")
        tmp = root / INBOX_DIR / f"{cid}.kpp.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ipfs", "get", "-o", str(tmp), cid], check=True)
        path = tmp

    if not path.exists():
        raise FileNotFoundError(path)

    items = _load_pack_items(path)
    meta: dict[str, Any] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            meta = raw
    except Exception:
        meta = {}

    book = book_override or meta.get("book") or ""
    subject = subject_override or meta.get("subject") or ""
    if not book or not subject:
        raise ValueError("包内缺少 book / subject，请用 --book / --subject 指定")

    if secret and meta and not verify_pack(meta, secret):
        raise ValueError("签名校验失败，已拒绝导入")

    known = set(valid_ids or [])
    accepted: dict[str, dict] = {}
    unknown: list[str] = []
    for it in items:
        qid = str(it.get("id") or "").strip()
        if not qid:
            continue
        if known and qid not in known:
            unknown.append(qid)
            continue
        ans = str(it.get("answer") or "").strip()
        sol = str(it.get("solution") or "").strip()
        if ans or sol:
            accepted[qid] = {"id": qid, "answer": ans, "solution": sol}

    conflicts = 0
    if accepted:
        existing = {i["id"]: i for i in collect_local_items(book, subject, root)}
        for qid, item in list(accepted.items()):
            old = existing.get(qid)
            if not old:
                continue
            conflicts += 1
            if strategy == "local":
                accepted[qid] = old
            elif strategy == "longest":
                accepted[qid] = {
                    "id": qid,
                    "answer": old["answer"] or item["answer"],
                    "solution": (old["solution"] if len(old["solution"]) >= len(item["solution"])
                                 else item["solution"]),
                }
        target_dir = solutions_root(root) / book / subject
        target_dir.mkdir(parents=True, exist_ok=True)
        author = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", str(meta.get("author") or "匿名"))[:24]
        out = target_dir / f"贡献_{author}_{path.stem[:24]}.json"
        out.write_text(json.dumps({
            "format": PACK_FORMAT, "book": book, "subject": subject,
            "author": meta.get("author", ""), "license": meta.get("license", ""),
            "imported_at": _now(), "count": len(accepted),
            "items": list(accepted.values()),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        written = str(out)
    else:
        written = ""

    return {"total": len(items), "accepted": len(accepted), "unknown_ids": unknown[:30],
            "unknown_count": len(unknown), "conflicts": conflicts, "written": written,
            "author": meta.get("author", ""), "license": meta.get("license", ""),
            "book": book, "subject": subject}


# --------------------------------------------------------------------------
# 待填模板 & 统计
# --------------------------------------------------------------------------
def gen_template(book: str, subject: SubjectType | str, questions: list[Any],
                 only_missing: bool = True, limit: int = 200) -> str:
    """生成待填答案模板（Markdown），供人工或 AI 批量填写后导入。"""
    sub = subject.value if isinstance(subject, SubjectType) else str(subject)
    lines = [f"# 答案/解析待填模板 · {book} · {sub}",
             "",
             "> 填写规则：每个 `## <题号>` 段写 【答案】与【解析】，可留空（留空的条目不会被导入）。",
             "> 填完保存为 .md 放到 solutions/<book>/<科目>/ 即可生效，或用导入工具导入。",
             ""]
    n = 0
    for q in questions:
        if getattr(q, "book", "") != book:
            continue
        if only_missing and (q.answer.strip() or q.solution.strip()):
            continue
        if n >= limit:
            break
        stem = re.sub(r"\s+", " ", q.stem).strip()
        lines.append(f"## {q.id}")
        lines.append(f"<!-- 章节：{q.chapter}｜题型：{q.question_type.value}｜题干摘要：{stem[:80]} -->")
        lines.append("【答案】")
        lines.append("【解析】")
        lines.append("")
        n += 1
    return "\n".join(lines)


def stats(root: Path | str | None = None) -> dict:
    """本地答案库统计：每本书/科目已回填数、来源文件与署名分布。"""
    root = Path(root) if root else bank_root()
    base = solutions_root(root)
    out: dict[str, dict] = {}
    if not base.exists():
        return out
    for book_dir in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for sub_dir in sorted(p for p in book_dir.iterdir() if p.is_dir()):
            items = collect_local_items(book_dir.name, sub_dir.name, root)
            authors: dict[str, int] = {}
            for f in sub_dir.rglob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                if isinstance(d, dict):
                    authors[d.get("author") or "匿名"] = authors.get(d.get("author") or "匿名", 0) + len(d.get("items", []))
            out[f"{book_dir.name}/{sub_dir.name}"] = {
                "entries": len(items),
                "with_answer": sum(1 for i in items if i["answer"]),
                "with_solution": sum(1 for i in items if i["solution"]),
                "authors": authors,
            }
    return out


def push_git(remote: str, branch: str = "main", root: Path | str | None = None,
             message: str = "chore: 更新答案贡献包", consent_required: bool = True) -> str:
    """把 outbox 提交并推送到**用户自己的**仓库。需先 write_consent(share=True)。"""
    root = Path(root) if root else bank_root()
    if consent_required and not read_consent(root).get("share"):
        raise PermissionError("未授权共享：请先开启共享授权（write_consent(share=True) 或界面勾选）")
    outbox = root / OUTBOX_DIR
    if not outbox.exists() or not any(outbox.glob("*.kpp.json")):
        raise ValueError("outbox 为空，没有可推送的贡献包")
    subprocess.run(["git", "add", str(outbox)], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(root), check=False)
    subprocess.run(["git", "push", remote, f"HEAD:{branch}"], cwd=str(root), check=True)
    return f"已推送到 {remote} ({branch})"
