from __future__ import annotations

import json
from typing import Any

_GENERIC_GUIDE_PHRASES = (
    "面对本节题目，先判断题型",
    "从资料中定位对应公式",
    "按资料中的例题步骤",
    "主线任务的目的不是复现资料",
    "结合摸底结果和用户备注动态调整复习优先级",
)


def _study_guide_issues(
    task: dict[str, Any],
    practice_by_id: dict[str, dict[str, Any]],
    *,
    require_self_test: bool = True,
    content_style: str = "standard",
) -> list[str]:
    task_id = str(task.get("id", ""))
    guide = task.get("studyGuide")
    if not isinstance(guide, dict):
        return [f"任务 {task_id} 缺少 studyGuide"]

    serialized = json.dumps(guide, ensure_ascii=False)
    issues = [
        f"任务 {task_id} 使用了通用占位讲解"
        for phrase in _GENERIC_GUIDE_PHRASES
        if phrase in serialized
    ]
    effective_style = str(task.get("_contentStyle") or content_style)
    if effective_style == "story":
        story_context = guide.get("storyContext")
        if not isinstance(story_context, dict):
            issues.append(f"任务 {task_id} 缺少故事上下文 storyContext")
            story_context = {}
        for key in ("setting", "mainEvent", "incomingQuestion", "outgoingQuestion"):
            if not str(story_context.get(key, "")).strip():
                issues.append(f"任务 {task_id} 的故事上下文缺少 {key}")
        characters = story_context.get("characters")
        if not isinstance(characters, list) or not any(str(item).strip() for item in characters):
            issues.append(f"任务 {task_id} 的故事上下文缺少主要人物")
        mappings = story_context.get("conceptMappings")
        if not isinstance(mappings, list) or not mappings:
            issues.append(f"任务 {task_id} 缺少故事到术语的 conceptMappings")
        elif any(
            not isinstance(mapping, dict)
            or not str(mapping.get("storyElement", "")).strip()
            or not str(mapping.get("concept", "")).strip()
            for mapping in mappings
        ):
            issues.append(f"任务 {task_id} 包含无效的故事概念映射")
        story_sections = guide.get("sections")
        expected_kinds = ("preparation", "explanation", "examples", "self-check")
        if not isinstance(story_sections, list):
            issues.append(f"任务 {task_id} 缺少故事章节 sections")
        else:
            actual_kinds = tuple(str(section.get("kind")) for section in story_sections if isinstance(section, dict))
            if len(story_sections) != 4 or actual_kinds != expected_kinds:
                issues.append(f"任务 {task_id} 的故事章节必须恰好按 preparation、explanation、examples、self-check 排列")
            by_kind = {str(section.get("kind")): section for section in story_sections if isinstance(section, dict)}
            for kind in expected_kinds:
                section = by_kind.get(kind)
                if not isinstance(section, dict):
                    issues.append(f"任务 {task_id} 缺少故事章节 {kind}")
                elif not str(section.get("title", "")).strip() or not str(section.get("narrative", "")).strip():
                    issues.append(f"任务 {task_id} 的故事章节 {kind} 缺少标题或叙事正文")
            preparation_section = by_kind.get("preparation", {})
            explanation_section = by_kind.get("explanation", {})
            examples_section = by_kind.get("examples", {})
            if isinstance(preparation_section, dict):
                questions = preparation_section.get("questions")
                if isinstance(questions, list) and len(questions) > 1:
                    issues.append(f"任务 {task_id} 的01课前准备只能有最多1个承上启下问题")
                terms = preparation_section.get("terms")
                if not isinstance(terms, list) or not terms:
                    issues.append(f"任务 {task_id} 的01课前准备缺少本节关键词解释")
                elif any(not isinstance(term, dict) or not str(term.get("term", "")).strip() or not str(term.get("meaning", "")).strip() or not str(term.get("role", "")).strip() for term in terms):
                    issues.append(f"任务 {task_id} 的01关键词必须逐个包含 term、meaning 和 role")
                if len(str(preparation_section.get("narrative", ""))) > 1000:
                    issues.append(f"任务 {task_id} 的01背景引导过长并侵占正式讲解职责")
            if isinstance(explanation_section, dict):
                beats = explanation_section.get("explanationBeats")
                if not isinstance(beats, list) or not 4 <= len(beats) <= 7:
                    issues.append(f"任务 {task_id} 的02讲解必须包含4至7个问题式或事件式 explanationBeats")
                elif any(not isinstance(beat, dict) or not str(beat.get("heading", "")).strip() or not str(beat.get("body", "")).strip() or not str(beat.get("conclusion", "")).strip() for beat in beats):
                    issues.append(f"任务 {task_id} 的02每个讲解标题必须包含 heading、body 和 conclusion")
                if not isinstance(explanation_section.get("methodSummary"), list) or not explanation_section.get("methodSummary"):
                    issues.append(f"任务 {task_id} 的02结尾缺少判断方法总结")
                if not str(explanation_section.get("transitionToExamples", "")).strip():
                    issues.append(f"任务 {task_id} 的02结尾没有自然引出03例题")
            if isinstance(examples_section, dict):
                examples = examples_section.get("workedExamples")
                if not isinstance(examples, list) or not 3 <= len(examples) <= 4:
                    issues.append(f"任务 {task_id} 的03必须包含1个主故事综合例题和2至3道独立变式")
                else:
                    variants = [example for example in examples if isinstance(example, dict) and example.get("independentVariant") is True]
                    if len(variants) not in {2, 3} or len(examples) - len(variants) != 1:
                        issues.append(f"任务 {task_id} 的03例题结构必须严格为1主例题+2至3独立变式")
                if not isinstance(examples_section.get("methodSummary"), list) or not examples_section.get("methodSummary"):
                    issues.append(f"任务 {task_id} 的03结尾缺少训练判断方法总结")
                if not str(examples_section.get("transitionToSelfCheck", "")).strip():
                    issues.append(f"任务 {task_id} 的03结尾没有说明04转为独立作答")
                story_event_ref = str(examples_section.get("storyEventRef", "")).strip()
                if not story_event_ref:
                    issues.append(f"任务 {task_id} 的主例题没有引用贯穿事件")
                elif story_event_ref != str(story_context.get("mainEvent", "")).strip():
                    issues.append(f"任务 {task_id} 的主例题引用与 mainEvent 不一致")

    elif guide.get("storyContext") is not None:
        issues.append(f"任务 {task_id} 的非故事版讲义不得包含 storyContext")

    exam_points = guide.get("examPoints")
    if not isinstance(exam_points, list) or not exam_points:
        issues.append(f"任务 {task_id} 没有根据资料动态规划考点")
        return issues

    exam_point_ids: set[str] = set()
    example_required_ids: set[str] = set()
    for point in exam_points:
        if not isinstance(point, dict):
            issues.append(f"任务 {task_id} 包含无效考点")
            continue
        point_id = str(point.get("id", "")).strip()
        if not point_id or point_id in exam_point_ids:
            issues.append(f"任务 {task_id} 的考点 id 缺失或重复")
            continue
        exam_point_ids.add(point_id)
        if not str(point.get("title", "")).strip() or not str(point.get("explanation", "")).strip():
            issues.append(f"任务 {task_id} 的考点 {point_id} 缺少标题或实质讲解")
        sources = point.get("sourceRefs")
        if not isinstance(sources, list) or not any(str(source).strip() for source in sources):
            issues.append(f"任务 {task_id} 的考点 {point_id} 缺少资料依据")
        teaching_mode = str(point.get("teachingMode", ""))
        if teaching_mode in {"calculation", "proof", "application"}:
            example_required_ids.add(point_id)
        formulas = point.get("formulas", [])
        if isinstance(formulas, list):
            for formula in formulas:
                if not isinstance(formula, dict) or not str(formula.get("expression", "")).strip():
                    issues.append(f"任务 {task_id} 的考点 {point_id} 存在空公式")
                    continue
                if not str(formula.get("meaning", "")).strip() or not str(formula.get("conditions", "")).strip():
                    issues.append(f"任务 {task_id} 的公式缺少含义或适用条件：{point_id}")

    covered_by_example: set[str] = set()
    worked_examples = guide.get("workedExamples", [])
    if not isinstance(worked_examples, list):
        issues.append(f"任务 {task_id} 的 workedExamples 格式无效")
        worked_examples = []
    for example in worked_examples:
        if not isinstance(example, dict):
            issues.append(f"任务 {task_id} 包含无效例题")
            continue
        required_text = ("problem", "analysis", "answer", "source")
        if any(not str(example.get(key, "")).strip() for key in required_text):
            issues.append(f"任务 {task_id} 的例题缺少题干、分析、答案或来源")
        steps = example.get("steps")
        if not isinstance(steps, list) or not any(str(step).strip() for step in steps):
            issues.append(f"任务 {task_id} 的例题缺少完整解题步骤")
        for point_id in example.get("examPointIds", []):
            covered_by_example.add(str(point_id))
    for point_id in sorted(example_required_ids - covered_by_example):
        issues.append(f"任务 {task_id} 的过程型考点 {point_id} 没有例题覆盖")

    if not require_self_test:
        return issues

    self_test_ids = guide.get("selfTestQuestionIds")
    if not isinstance(self_test_ids, list) or not self_test_ids:
        issues.append(f"任务 {task_id} 没有配置覆盖考点的自测题")
        return issues
    covered_by_test: set[str] = set()
    for question_id in self_test_ids:
        question = practice_by_id.get(str(question_id))
        if question is None:
            issues.append(f"任务 {task_id} 引用了不存在的自测题 {question_id}")
            continue
        if str(question.get("taskId", "")) != task_id:
            issues.append(f"自测题 {question_id} 未正确关联任务 {task_id}")
        covered_by_test.update(str(point_id) for point_id in question.get("examPointIds", []))
    for point_id in sorted(exam_point_ids - covered_by_test):
        issues.append(f"任务 {task_id} 的考点 {point_id} 没有被自测题覆盖")
    return issues


def _deterministic_review(
    candidate: dict[str, Any],
    expected_days: int,
    daily_minutes: int,
    *,
    validate_daily_budget: bool = True,
    content_style: str = "story",
) -> list[str]:
    issues: list[str] = []
    required = ("assessmentProfile", "knowledgePoints", "tasks", "practiceQuestions", "mockQuestions")
    for key in required:
        if not candidate.get(key):
            issues.append(f"缺少 {key}")
    point_ids = {
        str(point.get("id"))
        for point in candidate.get("knowledgePoints", [])
        if isinstance(point, dict) and point.get("id")
    }
    practice_by_id = {
        str(question.get("id")): question
        for question in candidate.get("practiceQuestions", [])
        if isinstance(question, dict) and question.get("id")
    }
    practice_ids = [
        str(question.get("id"))
        for question in candidate.get("practiceQuestions", [])
        if isinstance(question, dict) and question.get("id")
    ]
    if len(practice_ids) != len(set(practice_ids)):
        issues.append("practiceQuestions 包含重复题目 id")
    task_days: dict[int, int] = {}
    for task in candidate.get("tasks", []):
        if not isinstance(task, dict):
            issues.append("任务包含非对象项")
            continue
        if str(task.get("kind", "")) == "orientation":
            continue
        day = int(task.get("day", 0))
        task_days[day] = task_days.get(day, 0) + int(task.get("duration", 0))
        if str(task.get("knowledgePointId", "")) not in point_ids:
            issues.append(f"任务 {task.get('id', '')} 引用了不存在的知识点")
        if not str(task.get("source", "")).strip():
            issues.append(f"任务 {task.get('id', '')} 缺少来源")
        issues.extend(_study_guide_issues({**task, "_contentStyle": content_style}, practice_by_id))
    if validate_daily_budget:
        for day in range(1, expected_days + 1):
            total = task_days.get(day, 0)
            if total < int(daily_minutes * 0.8) or total > daily_minutes:
                issues.append(f"第{day}天任务时长 {total} 分钟，不符合预算 {daily_minutes} 分钟")
    for collection in ("practiceQuestions", "mockQuestions"):
        for question in candidate.get(collection, []):
            if not isinstance(question, dict):
                issues.append(f"{collection} 包含非对象项")
                continue
            question_type = str(question.get("type", "single")).strip()
            is_written_mock = collection == "mockQuestions" and question_type == "calculation"
            options = question.get("options", [])
            answer_index = question.get("answerIndex")
            if is_written_mock:
                if not str(question.get("referenceAnswer", "")).strip():
                    issues.append(f"题目 {question.get('id', '')} 缺少计算题参考答案")
            elif not isinstance(options, list) or len(options) < 2 or not isinstance(answer_index, int) or not 0 <= answer_index < len(options):
                issues.append(f"题目 {question.get('id', '')} 的选项或答案无效")
    return list(dict.fromkeys(issues))[:20]


def _select_missing_lesson_tasks(tasks: list[dict[str, Any]], lesson_limit: int | None) -> list[dict[str, Any]]:
    """Return the next missing non-orientation lessons in stable mainline order."""
    missing = [
        task
        for task in sorted(tasks, key=lambda item: (int(item.get("day", 0)), int(item.get("order", 0))))
        if str(task.get("kind", "")) != "orientation" and not isinstance(task.get("studyGuide"), dict)
    ]
    return missing[:lesson_limit] if lesson_limit is not None else missing


def _plan_issues(
    candidate: dict[str, Any],
    expected_days: int,
    daily_minutes: int,
    *,
    validate_daily_budget: bool = True,
) -> list[str]:
    issues: list[str] = []
    for key in ("assessmentProfile", "knowledgePoints", "tasks"):
        if not candidate.get(key):
            issues.append(f"缺少 {key}")
    point_ids = {
        str(point.get("id"))
        for point in candidate.get("knowledgePoints", [])
        if isinstance(point, dict) and point.get("id")
    }
    task_ids: set[str] = set()
    task_days: dict[int, int] = {}
    for task in candidate.get("tasks", []):
        if not isinstance(task, dict):
            issues.append("任务规划包含非对象项")
            continue
        if str(task.get("kind", "")) == "orientation":
            continue
        task_id = str(task.get("id", "")).strip()
        if not task_id or task_id in task_ids:
            issues.append("任务 id 缺失或重复")
        task_ids.add(task_id)
        day = int(task.get("day", 0))
        duration = int(task.get("duration", 0))
        task_days[day] = task_days.get(day, 0) + duration
        if str(task.get("knowledgePointId", "")) not in point_ids:
            issues.append(f"任务 {task_id} 引用了不存在的知识点")
        if not str(task.get("title", "")).strip() or not str(task.get("description", "")).strip():
            issues.append(f"任务 {task_id} 缺少标题或规划理由")
        if not str(task.get("source", "")).strip():
            issues.append(f"任务 {task_id} 缺少来源")
    if validate_daily_budget:
        for day in range(1, expected_days + 1):
            total = task_days.get(day, 0)
            if total < int(daily_minutes * 0.8) or total > daily_minutes:
                issues.append(f"第{day}天任务时长 {total} 分钟，不符合预算 {daily_minutes} 分钟")
    return list(dict.fromkeys(issues))
