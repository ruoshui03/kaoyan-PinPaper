"""
真题章节分布模型：{题型: {章名: 权重}}，组卷时作为软偏好（缺文件则空 dict，特性静默不启用）。

原本散落在 app.py 里，server.py 用不到 → Web 端组卷没有真题热点偏向。抽出来共用，
并加一层缓存，避免每次组卷都重读磁盘。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from core.bank_registry import bank_root

DIST_FILE = "真题章节分布.json"


def _normalize(block: dict) -> dict[str, dict[str, float]]:
    return {str(qt): {str(ch): float(w) for ch, w in m.items()}
            for qt, m in block.items() if isinstance(m, dict)}


@lru_cache(maxsize=8)
def load_chapter_dist(subject: str | None = None,
                      root: str | None = None) -> dict[str, dict[str, float]]:
    """读取真题章节分布。

    文件结构为 {科目: {题型: {章名: 权重}}}。
    - subject 为空：返回 {科目: {题型: {章: 权重}}}（app.py 用法）
    - 指定 subject：返回 {题型: {章: 权重}}（引擎 chapter_weights 用法）
    文件缺失或结构异常 → 空 dict，特性静默不启用。
    """
    root_path = Path(root) if root else bank_root()
    p = root_path / "题库资料" / DIST_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    if subject:
        return _normalize(data.get(subject, {}))
    return {str(sub): _normalize(v) for sub, v in data.items() if isinstance(v, dict)}


def scale_dist(dist: dict[str, dict[str, float]], strength: float) -> dict[str, dict[str, float]]:
    """按强度缩放权重：strength=0 → 不启用；1 → 完全按真题分布。

    w' = 1 + (w - 1) * strength，权重 1.0 的章保持中性。
    """
    s = max(0.0, min(1.0, float(strength)))
    if s <= 0 or not dist:
        return {}
    return {qt: {ch: 1.0 + (w - 1.0) * s for ch, w in m.items()} for qt, m in dist.items()}
