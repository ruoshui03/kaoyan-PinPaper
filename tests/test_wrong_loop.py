"""错题闭环回归：重练答对 → 自动移出活跃待练池；答错/未答 → 进错题本。

覆盖 server.py /api/submit-answers 背后的状态流转，避免哪天改判分逻辑把闭环改没。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_manager import StateManager  # noqa: E402


def _mgr(tmp_path: Path) -> StateManager:
    return StateManager(data_file=tmp_path / "state.json")


def test_batch_mark_solved_correctly_moves_out_of_pool(tmp_path):
    m = _mgr(tmp_path)
    m.batch_mark_wrong(["q1", "q2", "q3"])
    assert m.get_active_wrong_question_ids() == {"q1", "q2", "q3"}

    n = m.batch_mark_solved_correctly(["q1", "q3"])
    assert n == 2, f"应有 2 题状态发生变化，实际 {n}"
    assert m.get_active_wrong_question_ids() == {"q2"}, "答对的题要移出待练池"
    # 记录本身保留（保留做错次数用于加权），只是不再活跃
    assert m.is_wrong_marked("q1"), "移出待练池不等于从错题本删除"
    assert not m.is_in_active_pool("q1")


def test_batch_mark_solved_correctly_ignores_new_questions(tmp_path):
    """答对的新题不该被塞进错题本（否则错题本会被答对的题灌满）。"""
    m = _mgr(tmp_path)
    n = m.batch_mark_solved_correctly(["new-1", "new-2"])
    assert n == 0
    assert m.wrong_questions == {}, "答对的新题不应产生错题记录"


def test_mark_solved_correctly_single_keeps_legacy_behavior(tmp_path):
    m = _mgr(tmp_path)
    m.mark_solved_correctly("legacy-1")
    assert "legacy-1" in m.wrong_questions, "单题接口保持原语义：缺席时建记录"
    assert m.wrong_questions["legacy-1"].is_active_in_pool is False


def test_repeat_mastered_is_idempotent(tmp_path):
    m = _mgr(tmp_path)
    m.batch_mark_wrong(["q1"])
    assert m.batch_mark_solved_correctly(["q1"]) == 1
    assert m.batch_mark_solved_correctly(["q1"]) == 0, "重复提交不该重复计数"


def test_full_loop_wrong_then_correct(tmp_path):
    """一次完整的判分流转：错 → 进池；重练答对 → 出池；再错 → 回池。"""
    m = _mgr(tmp_path)
    m.batch_mark_wrong(["a", "b"])
    assert m.get_active_wrong_question_ids() == {"a", "b"}

    m.batch_mark_solved_correctly(["a"])          # 第一次重练：a 答对
    assert m.get_active_wrong_question_ids() == {"b"}

    m.batch_mark_wrong(["a"])                     # 第二次又错：a 回池
    assert m.get_active_wrong_question_ids() == {"a", "b"}
    assert m.get_wrong_count("a") == 2, "做错次数应累加，供组卷加权"
