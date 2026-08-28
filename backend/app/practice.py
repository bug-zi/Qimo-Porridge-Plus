"""练习/错题/模拟卷域（阶段2-5 从 study_service.py 抽取）。

职责：刷题作答与错题重做判分（submit_practice_answer / submit_wrong_answer_retry）、
错题记录与 AI 举一反三、掌握度/任务优先级联动、模拟卷修复与整卷计分
（含计算题 AI 批改）、练习作答清除。

依赖方向：practice → study_scheduler / agents（question_generation /
answer_consistency / with_structured_formula_rules），禁止模块级
import study_service（成环）。load_workspace / save_workspace /
get_course_prompt / _model_completion / _model_json / _extract_json /
_content_generation_lock / _workspace_is_planned / _review_session_days
属于跨域缝合点——测试惯用 monkeypatch.setattr(study_service, ...) 打桩，
故本模块在函数体内延迟 import study_service，调用时读取其（可能已被
patch 的）命名空间，打桩面与拆分前完全一致（workspace.py 既有惯例）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from . import study_scheduler
from .agents import with_structured_formula_rules
from .agents.answer_consistency import reconcile_question_answer
from .agents.question_generation import (
    _shuffle_single_choice_questions,
    mock_questions_need_repair,
)


def _find_question(workspace: dict[str, Any], question_id: str) -> dict[str, Any]:
    for question in workspace.get("practiceQuestions", []) + workspace.get("mockQuestions", []):
        if question.get("id") == question_id:
            return question
    raise KeyError("未找到题目")


def _find_any_question(workspace: dict[str, Any], question_id: str) -> dict[str, Any]:
    question_groups = (
        workspace.get("practiceQuestions", []),
        workspace.get("mockQuestions", []),
        workspace.get("diagnosticQuestions", []),
    )
    for questions in question_groups:
        for question in questions:
            if isinstance(question, dict) and str(question.get("id")) == question_id:
                return question
    raise KeyError("错题对应的原题已不存在")


def _answer_label(question: dict[str, Any], answer_index: int) -> str:
    options = question.get("options")
    if not isinstance(options, list):
        options = []
    if answer_index < 0:
        return "未作答"
    if answer_index >= len(options):
        return "不会"
    return str(options[answer_index])


def _is_written_mock_question(question: dict[str, Any]) -> bool:
    question_type = str(question.get("type", "single")).strip()
    label = str(question.get("questionType", "")).strip()
    return question_type == "calculation" or any(
        keyword in label
        for keyword in ("计算", "综合", "填空", "简答", "论述", "证明")
    )


def _grade_mock_written_answer(
    workspace: dict[str, Any],
    question: dict[str, Any],
    user_answer: str,
) -> tuple[int, bool, str]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _extract_json,
        _model_completion,
        build_model_messages,
        get_course_prompt,
    )

    max_score = int(question.get("score", 0))
    if not user_answer.strip():
        return 0, False, "本题未作答。"

    reference_answer = str(question.get("referenceAnswer") or question.get("answer") or "").strip()
    rubric = question.get("gradingRubric") if isinstance(question.get("gradingRubric"), list) else []
    prompt = with_structured_formula_rules("""
你是大学期末模拟卷阅卷 Agent。请按参考答案和评分要点批改一道计算题/综合题。
只返回 JSON 对象：
{"earnedScore":0到满分的整数,"correct":true或false,"explanation":"说明得分依据、关键错误或正确步骤"}
规则：允许与参考答案等价的表达；有过程分；如果最终答案对但过程明显缺失，可酌情扣分；如果用户答案空泛或没有计算依据，不给高分。
""")
    payload = {
        "course": workspace.get("course", {}),
        "question": question,
        "maxScore": max_score,
        "referenceAnswer": reference_answer,
        "gradingRubric": rubric,
        "userAnswer": user_answer,
    }
    try:
        parsed = _extract_json(
            _model_completion(
                build_model_messages(
                    prompt,
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    course_prompt=get_course_prompt(str(workspace.get("course", {}).get("id"))),
                ),
                json_mode=True,
            )
        )
        earned_score = max(0, min(max_score, int(parsed.get("earnedScore", 0))))
        explanation = str(parsed.get("explanation") or question.get("explanation") or "").strip()
        is_correct = bool(parsed.get("correct")) or earned_score >= max_score * 0.8
        return earned_score, is_correct, explanation
    except Exception as error:
        reference_text = reference_answer or str(question.get("explanation", "")).strip()
        is_correct = bool(reference_text and user_answer.strip() and user_answer.strip() in reference_text)
        earned_score = max_score if is_correct else 0
        explanation = (
            str(question.get("explanation", "")).strip()
            or f"AI 批改暂不可用：{error}"
        )
        return earned_score, is_correct, explanation


def _record_written_wrong_answer(
    workspace: dict[str, Any],
    question: dict[str, Any],
    user_answer: str,
    analysis: str,
    *,
    mode: str,
) -> None:
    wrong_answers = workspace.setdefault("wrongAnswers", [])
    question_id = str(question.get("id"))
    current = next((item for item in wrong_answers if item.get("id") == question_id), None)
    mistake_type = f"你的作答：{user_answer or '未作答'}。{analysis}"
    if current:
        current["count"] = int(current.get("count", 1)) + 1
        current["isReviewed"] = False
        current["mistakeType"] = mistake_type
        current.setdefault("questionId", question_id)
        current.setdefault("questionType", mode)
        current.setdefault("source", str(question.get("source", "课程题库")))
        current.setdefault("addedAt", datetime.now().isoformat(timespec="seconds"))
        return

    wrong_answers.insert(
        0,
        {
            "id": question_id,
            "questionId": question_id,
            "questionType": mode,
            "source": str(question.get("source", "课程题库")),
            "addedAt": datetime.now().isoformat(timespec="seconds"),
            "title": question.get("prompt", "错题"),
            "tag": _knowledge_point_name(workspace, str(question.get("knowledgePointId", ""))),
            "mistakeType": mistake_type,
            "count": 1,
            "isReviewed": False,
        },
    )


def _knowledge_point_name(workspace: dict[str, Any], knowledge_point_id: str) -> str:
    return next(
        (
            str(point.get("name"))
            for point in workspace.get("knowledgePoints", [])
            if isinstance(point, dict) and point.get("id") == knowledge_point_id
        ),
        str(workspace.get("course", {}).get("name") or "当前课程"),
    )


def _normalize_generated_practice_questions(
    questions: Any,
    *,
    base_question: dict[str, Any],
    knowledge_point_id: str,
) -> list[dict[str, Any]]:
    if not isinstance(questions, list):
        return []
    normalized: list[dict[str, Any]] = []
    base_id = str(base_question.get("id", "wrong"))
    for index, question in enumerate(questions[:3], start=1):
        if not isinstance(question, dict):
            continue
        options = question.get("options")
        answer_index = question.get("answerIndex")
        if not isinstance(options, list) or len(options) < 4:
            continue
        if not isinstance(answer_index, int) or answer_index < 0 or answer_index >= min(len(options), 5):
            continue
        prompt = str(question.get("prompt", "")).strip()
        explanation = str(question.get("explanation", "")).strip()
        if not prompt or not explanation:
            continue
        fingerprint = hashlib.sha1(f"{base_id}|{prompt}".encode("utf-8")).hexdigest()[:10]
        normalized.append(
            {
                "id": f"ai-similar-{base_id}-{fingerprint}",
                "type": "single",
                "score": int(question.get("score", base_question.get("score", 5))),
                "prompt": prompt,
                "options": [str(option) for option in options[:5]],
                "answerIndex": answer_index,
                "explanation": explanation,
                "knowledgePointId": str(question.get("knowledgePointId") or knowledge_point_id),
                "source": str(question.get("source") or f"AI 举一反三 / {base_question.get('source', '错题回顾')}"),
            }
        )
    _shuffle_single_choice_questions(normalized)
    return normalized


def _append_practice_questions(workspace: dict[str, Any], questions: list[dict[str, Any]]) -> int:
    if not questions:
        return 0
    practice_questions = workspace.setdefault("practiceQuestions", [])
    existing_ids = {str(question.get("id")) for question in practice_questions if isinstance(question, dict)}
    existing_prompts = {str(question.get("prompt")) for question in practice_questions if isinstance(question, dict)}
    added = 0
    for question in questions:
        if question["id"] in existing_ids or question["prompt"] in existing_prompts:
            continue
        practice_questions.append(question)
        existing_ids.add(question["id"])
        existing_prompts.add(question["prompt"])
        added += 1
    return added


def _ai_review_wrong_answer(
    workspace: dict[str, Any],
    question: dict[str, Any],
    answer_index: int,
    *,
    mode: str,
) -> tuple[str, int]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _extract_json,
        _model_completion,
        build_model_messages,
        get_course_prompt,
    )

    course_id = str(workspace.get("course", {}).get("id"))
    knowledge_point_id = str(question.get("knowledgePointId", ""))
    selected_label = _answer_label(question, answer_index)
    correct_label = _answer_label(question, int(question.get("answerIndex", -1)))
    answer_summary = f"{mode}失分：你选了「{selected_label}」，正确答案是「{correct_label}」。"
    base_analysis = (
        f"{answer_summary}{question.get('explanation', '')}"
    )
    point = next(
        (
            item
            for item in workspace.get("knowledgePoints", [])
            if isinstance(item, dict) and item.get("id") == knowledge_point_id
        ),
        {},
    )
    prompt = with_structured_formula_rules("""
你是大学期末速成 Agent。用户刚做错一道单选题。
请实时给出错题解析，并基于同一知识点举一反三生成 2 道新的单选练习题。
只返回 JSON 对象：
{
  "analysis":"用 2-4 句话说明为什么错、正确解法、下次如何判断",
  "questions":[{"id":"英文短横线 id","type":"single","score":5,"prompt":"...","options":["...","...","...","..."],"answerIndex":0-3,"explanation":"...","knowledgePointId":"...","source":"AI 举一反三"}]
}
要求：新题必须与原题同考点但不能只是替换选项文字；解析要能独立看懂。
""")
    payload = {
        "mode": mode,
        "course": workspace.get("course", {}),
        "knowledgePoint": point,
        "question": question,
        "selectedAnswer": selected_label,
        "correctAnswer": correct_label,
    }
    try:
        parsed = _extract_json(
            _model_completion(
                build_model_messages(
                    prompt,
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    course_prompt=get_course_prompt(course_id),
                ),
                json_mode=True,
            )
        )
    except Exception:
        return base_analysis, 0

    ai_analysis = str(parsed.get("analysis") or "").strip()
    analysis = f"{answer_summary}{ai_analysis}" if ai_analysis else base_analysis
    similar_questions = _normalize_generated_practice_questions(
        parsed.get("questions"),
        base_question=question,
        knowledge_point_id=knowledge_point_id,
    )
    added_count = _append_practice_questions(workspace, similar_questions)
    if added_count:
        analysis = f"{analysis} 已为你补充 {added_count} 道同类练习题。"
    return analysis, added_count


def _record_wrong_answer(
    workspace: dict[str, Any],
    question: dict[str, Any],
    answer_index: int,
    *,
    mode: str,
    wrong_answer_id: str | None = None,
) -> tuple[str, int]:
    analysis, added_count = _ai_review_wrong_answer(workspace, question, answer_index, mode=mode)
    wrong_answers = workspace.setdefault("wrongAnswers", [])
    question_id = str(question.get("id"))
    record_id = wrong_answer_id or question_id
    current = next((item for item in wrong_answers if item.get("id") == record_id), None)
    if current:
        current["count"] = int(current.get("count", 1)) + 1
        current["isReviewed"] = False
        current["mistakeType"] = analysis
        current.setdefault("questionId", question_id)
        current.setdefault("questionType", mode)
        current.setdefault("source", str(question.get("source", "课程题库")))
        current.setdefault("addedAt", datetime.now().isoformat(timespec="seconds"))
    else:
        wrong_answers.insert(
            0,
            {
                "id": record_id,
                "questionId": question_id,
                "questionType": mode,
                "source": str(question.get("source", "课程题库")),
                "addedAt": datetime.now().isoformat(timespec="seconds"),
                "title": question.get("prompt", "错题"),
                "tag": _knowledge_point_name(workspace, str(question.get("knowledgePointId", ""))),
                "mistakeType": analysis,
                "count": 1,
                "isReviewed": False,
            },
        )
    return analysis, added_count


def _update_mastery(workspace: dict[str, Any], knowledge_point_id: str, is_correct: bool) -> int:
    for point in workspace.get("knowledgePoints", []):
        if point.get("id") != knowledge_point_id:
            continue
        delta = 8 if is_correct else -3
        point["mastery"] = max(0, min(100, int(point.get("mastery", 40)) + delta))
        return point["mastery"]
    return 0


def _prioritize_tasks(workspace: dict[str, Any], knowledge_point_id: str, is_correct: bool) -> None:
    # 缝合点：_review_session_days 留在 study_service（复习计划域）。
    from .study_service import _review_session_days

    for task in workspace.get("tasks", []):
        if task.get("knowledgePointId") != knowledge_point_id:
            continue
        if is_correct:
            task["progress"] = min(100, int(task.get("progress", 0)) + 12)
            task["status"] = "completed" if task["progress"] >= 100 else "in-progress"
        else:
            task["priority"] = "high"
            task["description"] = f"{task['description']} 本题失分后已被置为优先复练。"

    onboarding_cfg = workspace.get("onboarding") or {}
    study_scheduler.reprioritize_pending(
        workspace["tasks"],
        workspace.get("knowledgePoints", []),
        session_days=_review_session_days(
            int(onboarding_cfg.get("days") or 0),
            int(onboarding_cfg.get("reviewCount") or 0),
        ),
        daily_minutes=round(float(onboarding_cfg.get("dailyHours") or 0) * 60) or 120,
        modules=workspace.get("modules") if isinstance(workspace.get("modules"), list) else None,
    )


def submit_practice_answer(
    question_id: str,
    answer_index: int,
    mode: str,
    course_id: str,
) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import load_workspace, record_learning_event, save_workspace

    workspace = load_workspace(course_id)
    question = _find_question(workspace, question_id)
    if question not in workspace.get("practiceQuestions", []):
        raise KeyError("该题不属于刷题练习")

    reconcile_question_answer(question)
    is_correct = int(question.get("answerIndex", -1)) == answer_index
    knowledge_point_id = question["knowledgePointId"]
    mastery = _update_mastery(workspace, knowledge_point_id, is_correct)
    _prioritize_tasks(workspace, knowledge_point_id, is_correct)

    explanation = str(question.get("explanation", ""))
    generated_similar_count = 0
    if not is_correct:
        explanation, generated_similar_count = _record_wrong_answer(
            workspace,
            question,
            answer_index,
            mode=mode,
        )

    workspace["diagnostic"] = {
        "estimatedScore": _estimate_score(workspace),
        "message": "已根据本次作答更新知识点掌握度与后续任务优先级。",
    }
    record_learning_event(
        course_id,
        mode,
        knowledge_point_id=str(knowledge_point_id),
        question_id=question_id,
        is_correct=is_correct,
        details={"title": str(question.get("prompt", "")), "mastery": mastery},
    )
    workspace.setdefault("practiceAnswers", {})[question_id] = {
        "answerIndex": answer_index,
        "correct": is_correct,
        "explanation": explanation,
        "mastery": mastery,
        "answeredAt": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
    }
    save_workspace(workspace, course_id)
    return {
        "correct": is_correct,
        "explanation": explanation,
        "mastery": mastery,
        "generatedSimilarCount": generated_similar_count,
        "workspace": workspace,
    }


def submit_wrong_answer_retry(
    wrong_answer_id: str,
    answer_index: int,
    course_id: str,
) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import load_workspace, record_learning_event, save_workspace

    workspace = load_workspace(course_id)
    wrong_answer = next(
        (item for item in workspace.get("wrongAnswers", []) if item.get("id") == wrong_answer_id),
        None,
    )
    if not isinstance(wrong_answer, dict):
        raise KeyError("未找到错题记录")

    question_id = str(wrong_answer.get("questionId") or wrong_answer_id)
    if question_id.startswith("diagnostic-"):
        question_id = question_id.removeprefix("diagnostic-")
    try:
        question = _find_any_question(workspace, question_id)
    except KeyError:
        if wrong_answer_id.startswith("diagnostic-"):
            question = _find_any_question(workspace, wrong_answer_id.removeprefix("diagnostic-"))
        else:
            raise

    reconcile_question_answer(question)
    is_correct = int(question.get("answerIndex", -1)) == answer_index
    knowledge_point_id = str(question.get("knowledgePointId", ""))
    mastery = _update_mastery(workspace, knowledge_point_id, is_correct)
    _prioritize_tasks(workspace, knowledge_point_id, is_correct)
    explanation = str(question.get("explanation", ""))
    generated_similar_count = 0

    if is_correct:
        wrong_answer["isReviewed"] = True
        wrong_answer["reviewedAt"] = datetime.now().isoformat(timespec="seconds")
    else:
        explanation, generated_similar_count = _record_wrong_answer(
            workspace,
            question,
            answer_index,
            mode="错题重做",
            wrong_answer_id=wrong_answer_id,
        )

    workspace["diagnostic"] = {
        "estimatedScore": _estimate_score(workspace),
        "message": "已根据错题重做结果更新掌握度和后续练习。",
    }
    record_learning_event(
        course_id,
        "错题重做",
        knowledge_point_id=knowledge_point_id,
        question_id=str(question.get("id", question_id)),
        is_correct=is_correct,
        details={"title": str(question.get("prompt", "")), "mastery": mastery},
    )
    save_workspace(workspace, course_id)
    return {
        "correct": is_correct,
        "explanation": explanation,
        "mastery": mastery,
        "generatedSimilarCount": generated_similar_count,
        "workspace": workspace,
    }


def _estimate_score(workspace: dict[str, Any]) -> str:
    points = workspace.get("knowledgePoints", [])
    if not points:
        return "未摸底"
    total_weight = sum(int(point.get("weight", 0)) for point in points) or 1
    weighted_mastery = sum(
        int(point.get("mastery", 0)) * int(point.get("weight", 0))
        for point in points
    ) / total_weight
    low = max(45, int(weighted_mastery * 0.65 + 28))
    high = min(96, low + 7)
    return f"{low}-{high} 分"


def repair_course_mock_questions(
    course_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Repair a missing/corrupt mock exam without regenerating the study plan.

    Existing questions are preserved unless force=True. The final write uses the
    workspace revision observed before the model call so concurrent learning updates
    cannot be overwritten by a slow repair request.
    """
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    # repair_mock_questions 也是打桩点——测试 patch study_service.repair_mock_questions。
    from .study_service import (
        _content_generation_lock,
        _model_json,
        _workspace_is_planned,
        get_course_prompt,
        load_workspace,
        repair_mock_questions,
        save_workspace,
    )

    generation_lock = _content_generation_lock(course_id)
    if not generation_lock.acquire(blocking=False):
        raise RuntimeError("当前课程已有内容生成任务正在运行，请等待它结束后再修复模拟卷。")
    try:
        workspace = load_workspace(course_id, refresh_materials=False)
        if not _workspace_is_planned(workspace):
            raise ValueError("请先完成摸底并生成复习主线，再生成模拟卷")
        if not workspace.get("knowledgePoints"):
            raise ValueError("课程尚无知识点，无法生成模拟卷")
        existing = workspace.get("mockQuestions")
        if not force and not mock_questions_need_repair(workspace):
            return {
                "workspace": workspace,
                "repaired": False,
                "source": "existing",
                "warning": "",
                "questionCount": len(existing),
            }

        expected_revision = int(workspace.get("revision", 0))
        course_prompt = ""
        try:
            course_prompt = get_course_prompt(course_id)
        except (FileNotFoundError, ValueError):
            pass
        result = repair_mock_questions(
            course_id,
            workspace,
            _model_json,
            course_prompt=course_prompt,
        )
        questions = result["mockQuestions"]
        workspace["mockQuestions"] = questions
        workspace["mockResult"] = None
        workspace["mockQuestionsGeneratedAt"] = datetime.now().isoformat(timespec="seconds")
        workspace["mockQuestionsGenerationSource"] = result["source"]
        workspace["mockQuestionsGenerationWarning"] = result["warning"]
        save_workspace(workspace, course_id, expected_revision=expected_revision)
        return {
            "workspace": workspace,
            "repaired": True,
            "source": result["source"],
            "warning": result["warning"],
            "questionCount": len(questions),
        }
    finally:
        generation_lock.release()


def submit_mock_answers(
    answers: dict[str, Any],
    course_id: str,
) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import load_workspace, record_learning_event, save_workspace

    workspace = load_workspace(course_id)
    questions = workspace.get("mockQuestions", [])
    if not questions:
        raise KeyError("模拟卷尚未生成")

    total_score = sum(int(question.get("score", 0)) for question in questions)
    earned_score = 0
    results: list[dict[str, Any]] = []
    for question in questions:
        question_score = int(question.get("score", 0))
        generated_similar_count = 0
        if _is_written_mock_question(question):
            user_answer = str(answers.get(question["id"], "")).strip()
            question_earned_score, is_correct, explanation = _grade_mock_written_answer(
                workspace,
                question,
                user_answer,
            )
            earned_score += question_earned_score
            if not is_correct:
                _record_written_wrong_answer(
                    workspace,
                    question,
                    user_answer,
                    explanation,
                    mode="模拟卷",
                )
        else:
            reconcile_question_answer(question)
            try:
                selected = int(answers.get(question["id"], -1))
            except (TypeError, ValueError):
                selected = -1
            is_correct = selected == int(question.get("answerIndex", -1))
            question_earned_score = question_score if is_correct else 0
            if is_correct:
                earned_score += question_score
            explanation = str(question.get("explanation", ""))
            if not is_correct:
                explanation, generated_similar_count = _record_wrong_answer(
                    workspace,
                    question,
                    selected,
                    mode="模拟卷",
                )
        mastery = _update_mastery(workspace, question["knowledgePointId"], is_correct)
        _prioritize_tasks(workspace, question["knowledgePointId"], is_correct)
        record_learning_event(
            course_id,
            "模拟卷",
            knowledge_point_id=str(question.get("knowledgePointId", "")),
            question_id=str(question.get("id", "")),
            is_correct=is_correct,
            details={"title": str(question.get("prompt", "")), "mastery": mastery, "earnedScore": question_earned_score},
        )
        results.append(
            {
                "id": question["id"],
                "correct": is_correct,
                "earnedScore": question_earned_score,
                "explanation": explanation,
                "mastery": mastery,
                "generatedSimilarCount": generated_similar_count,
            }
        )
    workspace["diagnostic"] = {
        "estimatedScore": _estimate_score(workspace),
        "message": "模拟卷已计分，后续任务已按失分知识点重新排序。",
    }
    workspace["mockResult"] = {
        "submittedAt": datetime.now().isoformat(timespec="seconds"),
        "score": earned_score,
        "total": total_score,
        "answers": {str(key): value for key, value in answers.items()},
        "results": results,
    }
    save_workspace(workspace, course_id)
    return {
        "score": earned_score,
        "total": total_score,
        "results": results,
        "workspace": workspace,
    }


def clear_practice_answer(question_id: str, course_id: str) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import load_workspace, save_workspace

    workspace = load_workspace(course_id, refresh_materials=False)
    practice_answers = workspace.get("practiceAnswers")
    if isinstance(practice_answers, dict) and practice_answers.pop(question_id, None) is not None:
        workspace["practiceAnswers"] = practice_answers
        save_workspace(workspace, course_id)
    return workspace


def clear_mock_result(course_id: str) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import load_workspace, save_workspace

    workspace = load_workspace(course_id, refresh_materials=False)
    workspace["mockResult"] = None
    save_workspace(workspace, course_id)
    return workspace

