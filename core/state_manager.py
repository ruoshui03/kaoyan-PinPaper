"""
考研数学智能组卷系统 - 状态管理与多用户错题本持久化服务 (Clean-Room 原创实现)
支持多用户/多科目独立隔离存储、做错次数追踪、错题本导入导出与跨设备迁移
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import QuestionItem, SubjectType, WrongQuestionRecord


class StateManager:
    """错题本管理与复习进度状态追踪服务（支持多用户与多科目档案隔离）"""

    def __init__(
        self,
        username: str = "default",
        subject: SubjectType | str | None = None,
        data_file: Path | str | None = None,
        base_dir: Path | str | None = None,
    ):
        self.subject = subject.value if isinstance(subject, SubjectType) else (str(subject) if subject else "")
        
        if data_file is not None:
            self.data_file = Path(data_file).resolve()
            self.username = self.data_file.stem
            self.storage_dir = self.data_file.parent
        else:
            self.username = self._clean_username(username)
            project_root = Path(__file__).resolve().parent.parent
            self.storage_dir = (Path(base_dir) if base_dir else project_root / "user_data").resolve()
            self.storage_dir.mkdir(parents=True, exist_ok=True)

            sub_suffix = f"_{self.subject}" if self.subject else ""
            default_file = self.storage_dir / f"wrong_notebook_default{sub_suffix}.json"
            target_file = self.storage_dir / f"wrong_notebook_{self.username}{sub_suffix}.json"
            legacy_file = project_root / "user_wrong_notebook.json"

            if not target_file.exists() or target_file.stat().st_size < 10:
                if default_file.exists() and default_file.stat().st_size > 10:
                    try:
                        target_file.write_text(default_file.read_text(encoding="utf-8"), encoding="utf-8")
                    except Exception:
                        pass
                elif legacy_file.exists() and not self.subject:
                    try:
                        target_file.write_text(legacy_file.read_text(encoding="utf-8"), encoding="utf-8")
                    except Exception:
                        pass

            self.data_file = target_file

        self.wrong_questions: dict[str, WrongQuestionRecord] = {}
        self.historical_seen_ids: set[str] = set()
        self.historical_covered_chapters: set[str] = set()
        self.last_papers_qids: list[list[str]] = []  # 上次生成的试卷（每份卷一个题号列表）
        self.load_state()

    @staticmethod
    def _clean_username(name: str) -> str:
        s = str(name).strip().replace(" ", "_").replace("/", "").replace("\\", "")
        return s if s else "default"

    def switch_user(self, new_username: str) -> None:
        """切换当前活跃用户档案"""
        cleaned = self._clean_username(new_username)
        if cleaned == self.username:
            return
        self.username = cleaned
        sub_suffix = f"_{self.subject}" if self.subject else ""
        self.data_file = self.storage_dir / f"wrong_notebook_{cleaned}{sub_suffix}.json"
        self.wrong_questions = {}
        self.historical_seen_ids = set()
        self.historical_covered_chapters = set()
        self.load_state()

    def get_all_profiles(self) -> list[str]:
        """获取本地已存储的所有用户档案名称"""
        profiles = set()
        for p in self.storage_dir.glob("wrong_notebook_*.json"):
            name = p.stem.replace("wrong_notebook_", "")
            # remove subject suffix if present
            for sub in ["_数学一", "_数学二", "_数学三"]:
                if name.endswith(sub):
                    name = name[:-len(sub)]
            if name:
                profiles.add(name)
        if not profiles:
            profiles.add("default")
        return sorted(profiles)

    def load_state(self) -> None:
        if not self.data_file.exists():
            return
        try:
            payload = json.loads(self.data_file.read_text(encoding="utf-8"))
            records = payload.get("wrong_questions", {})
            for qid, data in records.items():
                self.wrong_questions[qid] = WrongQuestionRecord(
                    question_id=qid,
                    added_at=data.get("added_at", ""),
                    user_note=data.get("user_note", ""),
                    error_tag=data.get("error_tag", "概念模糊"),
                    wrong_count=int(data.get("wrong_count", 1)),
                    is_active_in_pool=bool(data.get("is_active_in_pool", True)),
                    subject=data.get("subject", self.subject),
                )
            self.historical_seen_ids = set(payload.get("seen_question_ids", []))
            self.historical_covered_chapters = set(payload.get("covered_chapters", []))
            self.last_papers_qids = payload.get("last_papers_qids", []) or []
        except Exception:
            pass

    def save_state(self) -> None:
        try:
            payload = {
                "username": self.username,
                "subject": self.subject,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "wrong_questions": {
                    qid: rec.to_dict() for qid, rec in self.wrong_questions.items()
                },
                "seen_question_ids": list(self.historical_seen_ids),
                "covered_chapters": list(self.historical_covered_chapters),
                "last_papers_qids": self.last_papers_qids,
            }
            self.data_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def toggle_wrong_question(
        self,
        question_id: str,
        note: str = "",
        error_tag: str = "概念模糊",
    ) -> bool:
        if question_id in self.wrong_questions:
            del self.wrong_questions[question_id]
            is_added = False
        else:
            self.wrong_questions[question_id] = WrongQuestionRecord(
                question_id=question_id,
                user_note=note,
                error_tag=error_tag,
                wrong_count=1,
                is_active_in_pool=True,
                subject=self.subject,
            )
            is_added = True
        self.save_state()
        return is_added

    def remove_wrong_question(self, question_id: str) -> bool:
        if question_id in self.wrong_questions:
            del self.wrong_questions[question_id]
            self.save_state()
            return True
        return False

    def set_wrong_count(self, question_id: str, count: int) -> None:
        if count <= 0:
            if question_id in self.wrong_questions:
                del self.wrong_questions[question_id]
        else:
            if question_id in self.wrong_questions:
                self.wrong_questions[question_id].wrong_count = count
                self.wrong_questions[question_id].is_active_in_pool = True
            else:
                self.wrong_questions[question_id] = WrongQuestionRecord(
                    question_id=question_id,
                    wrong_count=count,
                    is_active_in_pool=True,
                    subject=self.subject,
                )
        self.save_state()

    def increment_wrong_count(self, question_id: str, delta: int = 1) -> int:
        if question_id in self.wrong_questions:
            rec = self.wrong_questions[question_id]
            rec.is_active_in_pool = True
            rec.wrong_count = max(1, rec.wrong_count + delta)
            self.save_state()
            return rec.wrong_count
        else:
            self.wrong_questions[question_id] = WrongQuestionRecord(
                question_id=question_id,
                wrong_count=max(1, delta),
                is_active_in_pool=True,
                subject=self.subject,
            )
            self.save_state()
            return self.wrong_questions[question_id].wrong_count

    def mark_solved_correctly(self, question_id: str) -> None:
        if question_id in self.wrong_questions:
            self.wrong_questions[question_id].is_active_in_pool = False
            self.save_state()
        else:
            self.wrong_questions[question_id] = WrongQuestionRecord(
                question_id=question_id,
                wrong_count=0,
                is_active_in_pool=False,
                subject=self.subject,
            )
            self.save_state()

    def reactivate_to_pool(self, question_id: str) -> None:
        if question_id in self.wrong_questions:
            self.wrong_questions[question_id].is_active_in_pool = True
            if self.wrong_questions[question_id].wrong_count <= 0:
                self.wrong_questions[question_id].wrong_count = 1
        else:
            self.wrong_questions[question_id] = WrongQuestionRecord(
                question_id=question_id,
                wrong_count=1,
                is_active_in_pool=True,
                subject=self.subject,
            )
        self.save_state()

    def is_in_active_pool(self, question_id: str) -> bool:
        rec = self.wrong_questions.get(question_id)
        return bool(rec and rec.is_active_in_pool and rec.wrong_count > 0)

    def is_temporarily_mastered(self, question_id: str) -> bool:
        rec = self.wrong_questions.get(question_id)
        return bool(rec and (not rec.is_active_in_pool) and rec.wrong_count > 0)

    def is_wrong_marked(self, question_id: str) -> bool:
        rec = self.wrong_questions.get(question_id)
        return bool(rec and rec.wrong_count > 0)

    def get_wrong_count(self, question_id: str) -> int:
        rec = self.wrong_questions.get(question_id)
        return rec.wrong_count if rec else 0

    def get_active_wrong_question_ids(self) -> set[str]:
        return {qid for qid, rec in self.wrong_questions.items() if rec.is_active_in_pool and rec.wrong_count > 0}

    def get_all_wrong_question_ids(self) -> set[str]:
        return set(self.wrong_questions.keys())

    def get_wrong_question_ids(self) -> set[str]:
        return self.get_active_wrong_question_ids()

    def get_active_wrong_pool(self) -> set[str]:
        return self.get_active_wrong_question_ids()

    def batch_mark_wrong(self, question_ids: list[str], error_tag: str = "概念模糊") -> int:
        count = 0
        for qid in question_ids:
            if qid not in self.wrong_questions:
                self.wrong_questions[qid] = WrongQuestionRecord(
                    question_id=qid,
                    error_tag=error_tag,
                    wrong_count=1,
                    is_active_in_pool=True,
                    subject=self.subject,
                )
                count += 1
            else:
                self.wrong_questions[qid].is_active_in_pool = True
                self.wrong_questions[qid].wrong_count += 1
                count += 1
        if count > 0:
            self.save_state()
        return count

    def batch_unmark_wrong(self, question_ids: list[str]) -> int:
        count = 0
        for qid in question_ids:
            if qid in self.wrong_questions:
                del self.wrong_questions[qid]
                count += 1
        if count > 0:
            self.save_state()
        return count

    def clear_all_wrong(self) -> None:
        self.wrong_questions.clear()
        self.save_state()

    def record_paper_generation(self, questions: list[QuestionItem]) -> None:
        for q in questions:
            self.historical_seen_ids.add(q.id)
            self.historical_covered_chapters.add(q.chapter)
        self.save_state()

    def set_last_papers(self, papers_qids: list[list[str]]) -> None:
        """记录上次生成的试卷题号（每份卷一个列表），落本地文件供重开恢复。"""
        self.last_papers_qids = papers_qids
        self.save_state()

    def reset_coverage_cycle(self) -> None:
        self.historical_covered_chapters.clear()
        self.save_state()

    def export_wrong_questions_json(self) -> str:
        payload = {
            "version": "1.0",
            "username": self.username,
            "subject": self.subject,
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(self.wrong_questions),
            "records": [rec.to_dict() for rec in self.wrong_questions.values()],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def import_wrong_questions_json(
        self,
        raw_json_str: str,
        valid_ids: set[str] | None = None,
        merge: bool = True,
    ) -> tuple[int, int]:
        """从 JSON 备份恢复错题。返回 (导入条数, 因题库变动被跳过的条数)。

        - valid_ids 提供时，仅导入当前题库仍存在的题号，其余跳过（跨版本安全）。
        - merge=True 合并进现有错题本；merge=False 先清空再导入。
        """
        data = json.loads(raw_json_str)
        records = data.get("records", [])
        if not merge:
            self.wrong_questions = {}
        imported = 0
        skipped = 0
        for item in records:
            qid = item.get("question_id")
            if not qid:
                continue
            if valid_ids is not None and qid not in valid_ids:
                skipped += 1
                continue
            self.wrong_questions[qid] = WrongQuestionRecord(
                question_id=qid,
                added_at=item.get("added_at", ""),
                user_note=item.get("user_note", ""),
                error_tag=item.get("error_tag", "概念模糊"),
                wrong_count=int(item.get("wrong_count", 1)),
                is_active_in_pool=bool(item.get("is_active_in_pool", True)),
                subject=item.get("subject", self.subject),
            )
            imported += 1
        self.save_state()
        return (imported, skipped)

    # =====================================================================
    # URL 位图编码：把错题状态压成可放进页面 URL 的紧凑串，实现无后端跨设备恢复
    # ---------------------------------------------------------------------
    # 每道题用 2 bit 记录状态（顺序 = 题库 canonical 顺序）：
    #   0 未标记 | 1 待练(错1次) | 2 待练·顽固(错≥2) | 3 历史错题(已归档)
    # 打包后 zlib 压缩(大量连续 0 压缩率极高) + urlsafe base64。
    # 串首带题库签名 sig，题库结构变化时签名不匹配即拒绝恢复，避免错位。
    # 注意：精确做错次数只保留"1 / ≥2"两档；自由备注/时间戳不进 URL。
    # =====================================================================
    URL_CODE_PREFIX = "w1"

    @staticmethod
    def bank_signature(ordered_ids: list[str]) -> str:
        """题库 canonical ID 列表的短签名，用于校验 URL 位图与当前题库是否匹配"""
        joined = "\n".join(ordered_ids)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]

    def _state_code_for(self, qid: str) -> int:
        rec = self.wrong_questions.get(qid)
        if not rec or rec.wrong_count <= 0:
            return 0
        if rec.is_active_in_pool:
            return 2 if rec.wrong_count >= 2 else 1
        return 3  # 已归档历史错题

    def to_url_code(self, ordered_ids: list[str]) -> str:
        """将当前科目错题状态编码为可放进 URL 的紧凑串"""
        n = len(ordered_ids)
        packed = bytearray((n + 3) // 4)
        for i, qid in enumerate(ordered_ids):
            code = self._state_code_for(qid)
            if code:
                packed[i >> 2] |= code << ((i & 3) * 2)
        compressed = zlib.compress(bytes(packed), 9)
        b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        return f"{self.URL_CODE_PREFIX}~{self.bank_signature(ordered_ids)}~{b64}"

    def apply_url_code(self, code: str, ordered_ids: list[str]) -> tuple[int, str]:
        """从 URL 串恢复错题状态。返回 (恢复的错题数, 状态说明)。

        - 前缀或格式不符 -> (0, 'invalid')
        - 题库签名不匹配 -> (0, 'stale')：题库已变，老链接失效，拒绝套用以免错位
        - 空错题(全 0)   -> (0, 'empty')：不覆盖本地已有数据
        - 成功           -> (个数, 'ok')
        """
        try:
            parts = code.split("~")
            if len(parts) != 3 or parts[0] != self.URL_CODE_PREFIX:
                return (0, "invalid")
            _, sig, b64 = parts
            if sig != self.bank_signature(ordered_ids):
                return (0, "stale")
            pad = "=" * (-len(b64) % 4)
            packed = zlib.decompress(base64.urlsafe_b64decode(b64 + pad))
        except Exception:
            return (0, "invalid")

        restored: dict[str, WrongQuestionRecord] = {}
        for i, qid in enumerate(ordered_ids):
            byte_i = i >> 2
            if byte_i >= len(packed):
                break
            code_val = (packed[byte_i] >> ((i & 3) * 2)) & 0b11
            if code_val == 0:
                continue
            if code_val == 1:
                restored[qid] = WrongQuestionRecord(question_id=qid, wrong_count=1, is_active_in_pool=True, subject=self.subject)
            elif code_val == 2:
                restored[qid] = WrongQuestionRecord(question_id=qid, wrong_count=2, is_active_in_pool=True, subject=self.subject)
            else:  # 3 历史
                restored[qid] = WrongQuestionRecord(question_id=qid, wrong_count=1, is_active_in_pool=False, subject=self.subject)

        if not restored:
            return (0, "empty")
        self.wrong_questions = restored
        self.save_state()
        return (len(restored), "ok")

    # =====================================================================
    # URL seen 位图:记录"已抽过的题",组卷时排除(每题 1 bit，比错题位图更省)。
    # 参数键 n1/n2/n3，与错题位图 d1/d2/d3 完全独立、共用 bank_signature。
    # 恢复语义是"合并"(seen 是单调累积集合，跨设备取并集)，不覆盖本地已有。
    # =====================================================================
    SEEN_CODE_PREFIX = "s1"

    def seen_to_url_code(self, ordered_ids: list[str]) -> str:
        """将当前科目"已抽过题"编码为可放进 URL 的紧凑串(1 bit/题)"""
        n = len(ordered_ids)
        packed = bytearray((n + 7) // 8)
        for i, qid in enumerate(ordered_ids):
            if qid in self.historical_seen_ids:
                packed[i >> 3] |= 1 << (i & 7)
        compressed = zlib.compress(bytes(packed), 9)
        b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        return f"{self.SEEN_CODE_PREFIX}~{self.bank_signature(ordered_ids)}~{b64}"

    def apply_seen_url_code(self, code: str, ordered_ids: list[str]) -> tuple[int, str]:
        """从 URL 串恢复"已抽过题"并**合并**进本地 seen 集合。返回 (恢复条数, 状态)。

        - 前缀/格式不符 -> (0, 'invalid')
        - 题库签名不匹配 -> (0, 'stale')
        - 空(全 0)      -> (0, 'empty')：不改动本地
        - 成功           -> (并入条数, 'ok')；seen 是累积集合，取并集而非覆盖
        """
        try:
            parts = code.split("~")
            if len(parts) != 3 or parts[0] != self.SEEN_CODE_PREFIX:
                return (0, "invalid")
            _, sig, b64 = parts
            if sig != self.bank_signature(ordered_ids):
                return (0, "stale")
            pad = "=" * (-len(b64) % 4)
            packed = zlib.decompress(base64.urlsafe_b64decode(b64 + pad))
        except Exception:
            return (0, "invalid")

        restored: set[str] = set()
        for i, qid in enumerate(ordered_ids):
            byte_i = i >> 3
            if byte_i >= len(packed):
                break
            if (packed[byte_i] >> (i & 7)) & 1:
                restored.add(qid)

        if not restored:
            return (0, "empty")
        self.historical_seen_ids |= restored  # 合并,不覆盖
        self.save_state()
        return (len(restored), "ok")

    # =====================================================================
    # URL 试卷编码：记住"上次生成的是哪几道题"，方便做完后跨设备查阅答案。
    # 规格无关：编码一个"试卷列表"，每份卷是变长的题号索引序列（索引=题号在 880
    # canonical 列表中的位置），故 5-3-3 / 自定义 / 3 套联考 全部统一支持。
    # 格式：p1~<sig>~<base64>，body = varint 结构：
    #   [卷数] 然后每份卷 [题数][idx*题数]，idx 用 2 字节小端（题库 <65536 题足够）。
    # sig 与位图共用 bank_signature，题库变化即判 stale，拒绝错位恢复。
    # =====================================================================
    PAPER_CODE_PREFIX = "p1"

    @staticmethod
    def encode_papers_code(papers_qids: list[list[str]], ordered_ids: list[str]) -> str:
        """把若干份试卷的题号列表编码为可放进 URL 的紧凑串。

        papers_qids: 每份卷一个题号列表（保持卷内原始顺序）。
        题号不在 canonical 列表中的会被跳过。
        """
        index_of = {qid: i for i, qid in enumerate(ordered_ids)}
        out = bytearray()
        out.append(min(len(papers_qids), 255))
        for qids in papers_qids:
            idxs = [index_of[q] for q in qids if q in index_of]
            out.append(min(len(idxs), 255))
            for idx in idxs[:255]:
                out += int(idx).to_bytes(2, "little")
        compressed = zlib.compress(bytes(out), 9)
        b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        sig = StateManager.bank_signature(ordered_ids)
        return f"{StateManager.PAPER_CODE_PREFIX}~{sig}~{b64}"

    @staticmethod
    def decode_papers_code(code: str, ordered_ids: list[str]) -> tuple[list[list[str]], str]:
        """从 URL 串还原试卷题号列表。返回 (每份卷的题号列表, 状态说明)。

        - 前缀/格式不符 -> ([], 'invalid')
        - 题库签名不匹配 -> ([], 'stale')
        - 成功 -> (papers_qids, 'ok')
        """
        try:
            parts = code.split("~")
            if len(parts) != 3 or parts[0] != StateManager.PAPER_CODE_PREFIX:
                return ([], "invalid")
            _, sig, b64 = parts
            if sig != StateManager.bank_signature(ordered_ids):
                return ([], "stale")
            pad = "=" * (-len(b64) % 4)
            data = zlib.decompress(base64.urlsafe_b64decode(b64 + pad))
        except Exception:
            return ([], "invalid")

        papers: list[list[str]] = []
        pos = 0
        if pos >= len(data):
            return ([], "invalid")
        n_papers = data[pos]; pos += 1
        n_ids = len(ordered_ids)
        for _ in range(n_papers):
            if pos >= len(data):
                break
            cnt = data[pos]; pos += 1
            qids: list[str] = []
            for _ in range(cnt):
                if pos + 2 > len(data):
                    break
                idx = int.from_bytes(data[pos:pos + 2], "little"); pos += 2
                if 0 <= idx < n_ids:
                    qids.append(ordered_ids[idx])
            papers.append(qids)
        return (papers, "ok")
