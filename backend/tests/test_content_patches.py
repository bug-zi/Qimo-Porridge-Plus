from copy import deepcopy

import pytest

from app.agents.content_patches import apply_guide_patches, apply_question_patches


def test_guide_patch_changes_only_target_field() -> None:
    guide = {"examPoints": [{"id": "ep1", "title": "原题"}], "storyContext": {"mainEvent": "事件"}}
    result = apply_guide_patches(guide, {"patches": [{"op": "replace", "path": "examPoints[0].title", "value": "新题"}]})
    assert result["examPoints"][0]["title"] == "新题"
    assert result["examPoints"][0]["id"] == "ep1"
    assert guide["examPoints"][0]["title"] == "原题"


def test_guide_patch_accepts_json_pointer_style_path() -> None:
    """回归：模型按 JSON Pointer 习惯返回 /sections/0/questions 曾被整串拒绝
    （现场：task-d3-03 讲义修复抛"讲义 patch 不允许修改路径"）。两种格式必须等价。"""
    guide = {"sections": [{"kind": "preparation", "questions": ["q1", "q2", "q3"]}]}
    result = apply_guide_patches(
        guide,
        {"patches": [{"op": "replace", "path": "/sections/0/questions", "value": ["只保留一个问题"]}]},
    )
    assert result["sections"][0]["questions"] == ["只保留一个问题"]
    # 点号格式仍等价工作
    result_dot = apply_guide_patches(
        guide,
        {"patches": [{"op": "replace", "path": "sections[0].questions", "value": ["点号格式"]}]},
    )
    assert result_dot["sections"][0]["questions"] == ["点号格式"]


def test_question_patch_accepts_json_pointer_style_path() -> None:
    questions = [{"id": "task-q1", "options": ["A", "B", "C", "D"], "taskId": "task"}]
    result = apply_question_patches(
        questions,
        {"patches": [{"op": "replace", "questionId": "task-q1", "path": "/options/1", "value": "改后选项"}]},
        "task",
    )
    assert result[0]["options"][1] == "改后选项"
    assert result[0]["options"][0] == "A"


def test_guide_patch_rejects_immutable_fields() -> None:
    with pytest.raises(ValueError):
        apply_guide_patches({"examPoints": [{"id": "ep1"}]}, {"patches": [{"op": "replace", "path": "examPoints[0].id", "value": "ep2"}]})


def test_question_patch_preserves_other_questions() -> None:
    questions = [{"id": "task-q1", "prompt": "旧题", "taskId": "task"}, {"id": "task-q2", "prompt": "不变", "taskId": "task"}]
    result = apply_question_patches(questions, {"patches": [{"op": "replace", "questionId": "task-q1", "path": "prompt", "value": "新题"}]}, "task")
    assert result[0]["prompt"] == "新题"
    assert result[1] == questions[1]


def test_question_patch_can_add_question_for_missing_point() -> None:
    result = apply_question_patches([], {"patches": [{"op": "add_question", "question": {"id": "task-q2", "taskId": "task", "examPointIds": ["ep2"], "prompt": "补题"}}]}, "task")
    assert result == [{"id": "task-q2", "taskId": "task", "examPointIds": ["ep2"], "prompt": "补题"}]


def test_question_patch_rejects_cross_task_question() -> None:
    with pytest.raises(ValueError):
        apply_question_patches([], {"patches": [{"op": "add_question", "question": {"id": "other-q", "taskId": "other"}}]}, "task")
