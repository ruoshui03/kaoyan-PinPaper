"""
答案 / 解析共享中心 CLI（去中心化、授权制）

    python tools/solutions_hub.py status                      查看本地答案库与授权状态
    python tools/solutions_hub.py consent --share --author 昵称 开启/关闭共享授权
    python tools/solutions_hub.py template --book 880 --subject 数学一 --out 待填.md
    python tools/solutions_hub.py import <文件|URL|CID> --book 880 --subject 数学一
    python tools/solutions_hub.py export --book 880 --subject 数学一 --author 昵称
    python tools/solutions_hub.py push-git --remote git@github.com:me/fork.git

默认不联网、不外发。只有 import 指定了 URL/CID、或 push-git 指定 remote 时才产生出网动作。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.bank_loader import BankLoader  # noqa: E402
from core import contribution as C  # noqa: E402
from core.models import SubjectType  # noqa: E402

SUBJECT_MAP = {"数学一": SubjectType.MATH_1, "数学二": SubjectType.MATH_2, "数学三": SubjectType.MATH_3}


def _ids_of(subject: SubjectType, book: str | None = None) -> set[str]:
    loader = BankLoader(subject=subject)
    qs = loader.load()
    if book:
        return {q.id for q in qs if getattr(q, "book", "") == book}
    return {q.id for q in qs}


def main() -> int:
    ap = argparse.ArgumentParser(description="答案/解析去中心化共享中心")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="查看本地答案库与授权状态")

    p = sub.add_parser("consent", help="设置共享授权")
    p.add_argument("--share", dest="share", action="store_true", help="开启共享")
    p.add_argument("--no-share", dest="no_share", action="store_true", help="关闭共享")
    p.add_argument("--author", default="", help="署名（可留空=匿名）")

    p = sub.add_parser("template", help="生成待填答案模板")
    p.add_argument("--book", required=True)
    p.add_argument("--subject", required=True, choices=list(SUBJECT_MAP))
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--out", default=None)

    p = sub.add_parser("import", help="导入贡献包（文件/URL/IPFS CID）")
    p.add_argument("source")
    p.add_argument("--book", default=None)
    p.add_argument("--subject", default=None, choices=list(SUBJECT_MAP))
    p.add_argument("--strategy", default="remote", choices=["remote", "local", "longest"])
    p.add_argument("--secret", default=None, help="签名校验密钥（可选）")

    p = sub.add_parser("export", help="导出本地贡献包到 solutions/_outbox")
    p.add_argument("--book", required=True)
    p.add_argument("--subject", required=True, choices=list(SUBJECT_MAP))
    p.add_argument("--author", default="")
    p.add_argument("--secret", default=None)

    p = sub.add_parser("push-git", help="推送 outbox 到你自己的仓库（需已开启共享授权）")
    p.add_argument("--remote", required=True)
    p.add_argument("--branch", default="main")

    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent

    if args.cmd == "status":
        consent = C.read_consent(root)
        print(f"共享授权: {'开启' if consent['share'] else '关闭'}   署名: {consent['author'] or '匿名'}"
              f"   更新于 {consent['updated_at'] or '—'}")
        st = C.stats(root)
        if not st:
            print("本地答案库为空。可用 template 生成待填模板。")
        for k, v in st.items():
            authors = "、".join(f"{a}×{n}" for a, n in v["authors"].items()) or "—"
            print(f"  {k:<24} 条目 {v['entries']:<5} 有答案 {v['with_answer']:<5} "
                  f"有解析 {v['with_solution']:<5} 来源: {authors}")
        return 0

    if args.cmd == "consent":
        share = True if args.share else (False if args.no_share else C.read_consent(root)["share"])
        path = C.write_consent(share=share, author=args.author, root=root)
        print(f"授权已写入 {path} → share={share}")
        return 0

    if args.cmd == "template":
        subject = SUBJECT_MAP[args.subject]
        loader = BankLoader(subject=subject)
        qs = loader.load()
        text = C.gen_template(args.book, subject, qs, limit=args.limit)
        out = Path(args.out) if args.out else root / f"solutions/_待填_{args.book}_{args.subject}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"模板已生成 {out}（{text.count('## ')} 题待填）")
        return 0

    if args.cmd == "import":
        subject_key = args.subject or ""
        known = _ids_of(SUBJECT_MAP[subject_key], args.book) if subject_key else set()
        try:
            res = C.import_pack(args.source, valid_ids=known or None, root=root,
                                strategy=args.strategy, book_override=args.book,
                                subject_override=subject_key, secret=args.secret)
        except Exception as e:
            print(f"导入失败: {e}")
            return 1
        print(f"包内 {res['total']} 条 → 采纳 {res['accepted']} 条"
              f"（题号不认识 {res['unknown_count']} 条，与本地冲突 {res['conflicts']} 条）")
        if res["unknown_ids"]:
            print("  未识别题号示例:", "、".join(res["unknown_ids"][:8]))
        if res["written"]:
            print(f"  已写入 {res['written']}")
        if res["license"]:
            print(f"  授权声明: {res['license']}｜贡献者: {res['author'] or '匿名'}")
        return 0

    if args.cmd == "export":
        try:
            out = C.export_pack(args.book, args.subject, root=root, author=args.author,
                                share=C.read_consent(root)["share"], secret=args.secret)
        except ValueError as e:
            print(str(e))
            return 1
        print(f"贡献包已导出 {out}")
        return 0

    if args.cmd == "push-git":
        try:
            print(C.push_git(args.remote, args.branch, root=root))
        except Exception as e:
            print(f"推送失败: {e}")
            return 1
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
