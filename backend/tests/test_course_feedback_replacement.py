from __future__ import annotations

from copy import deepcopy

from app.course_feedback_service import (
    _replace_scope_fallback,
    _replace_selection_fragments,
    _replace_story_section,
    _split_rewrite_sections,
    generate_rewrite_proposal,
)


def _guide() -> dict:
    point = {
        "id": "point-1",
        "title": "核心概念辨析",
        "explanation": "不同类别的概念不能直接混用。",
        "procedure": ["先阅读题目条件。", "再核对适用规则。"],
        "pitfalls": [],
    }
    return {"examPoints": [point], "sections": [{"examPoints": deepcopy([point])}]}


def test_replace_selection_fragments_across_fields_transactionally() -> None:
    guide = _guide()
    target = {
        "examPointId": "point-1",
        "sourceArea": "lesson_explanation",
        "selectionFragments": [
            {"field": "examPoint.explanation", "examPointId": "point-1", "selectedText": "类别的概念不能直接混用。"},
            {"field": "examPoint.procedure", "examPointId": "point-1", "itemIndex": "0", "selectedText": "先阅读题目条件。"},
        ],
    }

    assert _replace_selection_fragments(guide, target, "类别的概念不能直接混用。先阅读题目条件。", "先画图，再折算。")
    point = guide["examPoints"][0]
    assert point["explanation"] == "不同先画图，再折算。"
    assert point["procedure"][0] == ""


def test_replace_selection_fragments_rolls_back_if_any_anchor_is_stale() -> None:
    guide = _guide()
    before = deepcopy(guide)
    target = {
        "examPointId": "point-1",
        "sourceArea": "lesson_explanation",
        "selectionFragments": [
            {"field": "examPoint.explanation", "examPointId": "point-1", "selectedText": "类别的概念不能直接混用。"},
            {"field": "examPoint.procedure", "examPointId": "point-1", "itemIndex": "0", "selectedText": "已经变化的步骤"},
        ],
    }

    assert not _replace_selection_fragments(guide, target, "类别的概念不能直接混用。已经变化的步骤", "新文本")
    assert guide == before


def test_split_rewrite_sections_recovers_inline_numbering_and_headings() -> None:
    rewritten = (
        "【做题时怎么判断】1. 先看题干。2. 如果问状态就答进程。3. 如果问静态实体就答程序。"
        "【容易错的地方】1. 把程序等同于进程。2. 忽略 PCB。3. 混淆并发与并行。"
    )
    assert _split_rewrite_sections(rewritten) == {
        "explanation": "",
        "procedure": ["先看题干。", "如果问状态就答进程。", "如果问静态实体就答程序。"],
        "pitfalls": ["把程序等同于进程。", "忽略 PCB。", "混淆并发与并行。"],
    }


def test_split_rewrite_sections_handles_chinese_commas_circled_numbers_and_implicit_lists() -> None:
    assert _split_rewrite_sections("1，先看题干。2，判断状态。3，最后核对。") == {
        "explanation": "",
        "procedure": ["先看题干。", "判断状态。", "最后核对。"],
        "pitfalls": [],
    }
    assert _split_rewrite_sections("① 先看题干。② 判断状态。③ 最后核对。") == {
        "explanation": "",
        "procedure": ["先看题干。", "判断状态。", "最后核对。"],
        "pitfalls": [],
    }


def test_cross_field_rewrite_removes_empty_old_list_items_and_restores_layout() -> None:
    guide = _guide()
    target = {
        "examPointId": "point-1",
        "sourceArea": "lesson_explanation",
        "selectionFragments": [
            {"field": "examPoint.explanation", "examPointId": "point-1", "selectedText": "类别的概念不能直接混用。"},
            {"field": "examPoint.procedure", "examPointId": "point-1", "itemIndex": "0", "selectedText": "先阅读题目条件。"},
            {"field": "examPoint.procedure", "examPointId": "point-1", "itemIndex": "1", "selectedText": "再核对适用规则。"},
        ],
    }
    selected = "类别的概念不能直接混用。先阅读题目条件。再核对适用规则。"
    rewritten = "先理解定义。【做题时怎么判断】1. 看题干。2. 找条件。【容易错的地方】1. 不要混淆概念。"

    assert _replace_selection_fragments(guide, target, selected, rewritten)
    point = guide["examPoints"][0]
    assert point["explanation"] == "不同先理解定义。"
    assert point["procedure"] == ["看题干。", "找条件。"]
    assert point["pitfalls"] == ["不要混淆概念。"]


def test_rewrite_does_not_mutate_unselected_worked_examples() -> None:
    guide = _guide()
    guide["workedExamples"] = [{"id": "ex-1", "problem": "原题", "steps": ["原步骤"], "answer": "原答案"}]
    before_examples = deepcopy(guide["workedExamples"])
    target = {
        "examPointId": "point-1",
        "selectionFragments": [
            {"field": "examPoint.explanation", "examPointId": "point-1", "selectedText": "类别的概念不能直接混用。"},
            {"field": "examPoint.procedure", "examPointId": "point-1", "itemIndex": "0", "selectedText": "先阅读题目条件。"},
        ],
    }
    assert _replace_selection_fragments(guide, target, "类别的概念不能直接混用。先阅读题目条件。", "1，先看题干。2，判断条件。")
    assert guide["workedExamples"] == before_examples
    assert guide["examPoints"][0]["procedure"][:2] == ["先看题干。", "判断条件。"]


def test_pitfall_fragments_stay_in_pitfalls_and_preserve_explanation() -> None:
    guide = _guide()
    guide["examPoints"][0]["explanation"] = "原有讲解不得改动"
    guide["examPoints"][0]["procedure"] = ["原有步骤不得改动"]
    guide["examPoints"][0]["pitfalls"] = ["旧错点一", "旧错点二", "旧错点三"]
    target = {
        "examPointId": "point-1",
        "selectionFragments": [
            {"field": "examPoint.pitfalls", "examPointId": "point-1", "itemIndex": "0", "selectedText": "旧错点一"},
            {"field": "examPoint.pitfalls", "examPointId": "point-1", "itemIndex": "1", "selectedText": "旧错点二"},
            {"field": "examPoint.pitfalls", "examPointId": "point-1", "itemIndex": "2", "selectedText": "旧错点三"},
        ],
    }
    rewritten = "常见易错点：程序和进程的区分\n1. 新错点一\n错因：原因一。\n2. 新错点二\n错因：原因二。\n3. 新错点三\n错因：原因三。"

    assert _replace_selection_fragments(guide, target, "旧错点一旧错点二旧错点三", rewritten)
    point = guide["examPoints"][0]
    assert point["explanation"] == "原有讲解不得改动"
    assert point["procedure"] == ["原有步骤不得改动"]
    assert len(point["pitfalls"]) == 3
    assert point["pitfalls"][0].startswith("常见易错点：程序和进程的区分")
    assert all("旧错点" not in item for item in point["pitfalls"])


def test_replace_selection_fragments_rejects_unverified_selection_text() -> None:
    guide = _guide()
    before = deepcopy(guide)
    target = {
        "selectionFragments": [
            {"field": "examPoint.explanation", "examPointId": "point-1", "selectedText": "类别的概念不能直接混用。"},
            {"field": "examPoint.procedure", "examPointId": "point-1", "itemIndex": "0", "selectedText": "先阅读题目条件。"},
        ],
    }

    assert not _replace_selection_fragments(guide, target, "另一段文本", "新文本")
    assert guide == before


def test_story_question_can_be_deleted_by_exact_anchor() -> None:
    guide = {"sections": [{"kind": "preparation", "questions": ["保留问题", "删除问题"]}]}
    target = {"field": "storySection.questions", "sectionKind": "preparation", "itemIndex": "1"}
    assert _replace_story_section(guide, target, "删除问题", "")
    assert guide["sections"][0]["questions"] == ["保留问题"]


def test_delete_feedback_returns_preview_without_calling_model() -> None:
    def model_json(*_args):
        raise AssertionError("删除意见不应依赖模型返回非空文本")

    proposal = generate_rewrite_proposal(
        "course-1", "feedback-1", selected_text="需要删除的段落",
        user_comment="请直接把这段删掉", context={"taskId": "task-1"}, model_json=model_json,
    )
    assert proposal["rewrittenText"] == ""
    assert proposal["replaceable"] is True


def test_story_scope_replacement_accepts_formula_rendering_text_differences() -> None:
    narrative = "先判断等待对象：等 CPU 是就绪态，等 I/O 或事件是阻塞态。\n最后核对时间片。"
    selected = "先判断等待对象：等 CPU 是就绪态，等 I \nO 或事件是阻塞态。最后核对时间片。"
    guide = {"sections": [{"kind": "explanation", "narrative": narrative}]}
    target = {"sourceArea": "story_explanation", "taskId": "task-1"}

    assert _replace_scope_fallback(guide, target, selected, "三轮修改后的最终版本")
    assert guide["sections"][0]["narrative"] == "三轮修改后的最终版本"


def test_story_scope_replacement_rejects_unrelated_text() -> None:
    guide = {"sections": [{"kind": "explanation", "narrative": "原始故事讲解"}]}
    assert not _replace_scope_fallback(guide, {"sourceArea": "story_explanation"}, "完全无关文本", "新文本")
    assert guide["sections"][0]["narrative"] == "原始故事讲解"
