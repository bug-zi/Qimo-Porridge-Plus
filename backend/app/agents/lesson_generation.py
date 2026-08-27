from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .checkpoint_contracts import lesson_content_signature, lesson_guide_signature, lesson_questions_signature
from .content_prompts import LESSON_CONTENT_PROMPT, LESSON_PRACTICE_PROMPT
from .content_validation import _study_guide_issues
from .contracts import ReviewReport
from .lesson_fallbacks import _backup_practice_questions, _backup_study_guide
from .question_generation import _question_issues, _shuffle_single_choice_options, _strong_feedback_issues
from .readability_review import attach_readability_review
from .workflow_types import JsonModelCall
from ..agent_runtime import get_latest_artifact, save_artifact
from ..knowledge_service import retrieve_material_context


@dataclass(frozen=True)
class LessonRuntimeDeps:
    """Narrow side-effect ports used by one lesson build."""

    get_latest_artifact: Callable[..., dict[str, Any] | None] = get_latest_artifact
    save_artifact: Callable[..., dict[str, Any]] = save_artifact
    retrieve_material_context: Callable[..., dict[str, Any]] = retrieve_material_context
    shuffle_single_choice_options: Callable[[dict[str, Any]], dict[str, Any]] = _shuffle_single_choice_options


@dataclass
class LessonBuilder:
    course_id: str
    workspace: dict[str, Any]
    review_plan: str
    course_prompt: str
    evidence_context: str
    model_json: JsonModelCall
    run_id: str
    content_style: str
    style_contract: dict[str, object]
    strong_feedback_directives: list[str]
    point_by_id: dict[str, dict[str, Any]]
    ordered_lessons: list[dict[str, Any]]
    lesson_index_by_id: dict[str, int]
    check_cancelled: Callable[[], None]
    deps: LessonRuntimeDeps = LessonRuntimeDeps()

    def build(self, task: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]], ReviewReport, bool]:
        self.check_cancelled()
        task_id = str(task.get("id", ""))
        
        def normalize_practice_questions(raw_questions: list[dict[str, Any]], guide: dict[str, Any]) -> list[dict[str, Any]]:
            normalized: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            self_test_ids: list[str] = []
            for index, question in enumerate(raw_questions, start=1):
                if not isinstance(question, dict):
                    continue
                item = dict(question)
                raw_id = str(item.get("id") or f"q{index}").strip()
                question_id = raw_id if raw_id.startswith(f"{task_id}-") else f"{task_id}-{raw_id}"
                if question_id in seen_ids:
                    question_id = f"{task_id}-q{index}"
                suffix = 2
                base_question_id = question_id
                while question_id in seen_ids:
                    question_id = f"{base_question_id}-{suffix}"
                    suffix += 1
                seen_ids.add(question_id)
                item["id"] = question_id
                item["taskId"] = task_id
                item["knowledgePointId"] = str(task.get("knowledgePointId", item.get("knowledgePointId", "")))
                if not isinstance(item.get("examPointIds"), list):
                    item["examPointIds"] = []
                self.deps.shuffle_single_choice_options(item)
                normalized.append(item)
                self_test_ids.append(question_id)
            guide["selfTestQuestionIds"] = self_test_ids
            return normalized
        
        lesson_signature = lesson_content_signature(
            style_contract=self.style_contract,
            task=task,
            review_plan=self.review_plan,
            course_prompt=self.course_prompt,
        )
        artifact_type = f"lesson_content_checkpoint:{task_id}"
        cached_lesson = self.deps.get_latest_artifact(self.course_id, artifact_type)
        cached_content = cached_lesson.get("content", {}) if cached_lesson else {}
        if cached_content.get("signature") == lesson_signature:
            cached_guide = cached_content.get("studyGuide")
            cached_questions = cached_content.get("practiceQuestions")
            if isinstance(cached_guide, dict) and isinstance(cached_questions, list):
                cached_questions = normalize_practice_questions(cached_questions, cached_guide)
                cached_practice_by_id = {
                    str(question.get("id")): question
                    for question in cached_questions
                    if isinstance(question, dict) and question.get("id")
                }
                cached_issues = _study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": cached_guide}, cached_practice_by_id)
                cached_issues.extend(_strong_feedback_issues(cached_guide, self.strong_feedback_directives))
                cached_issues.extend(_question_issues(cached_questions, collection=f"任务 {task_id} 自测题"))
                if not cached_issues:
                    attach_readability_review({**task, "studyGuide": cached_guide}, self.content_style)
                    return task_id, cached_guide, cached_questions, ReviewReport(
                        passed=True,
                        issues=[],
                        source_coverage=1,
                        summary="已复用通过覆盖校验的学习单元检查点。",
                    ), False
        retrieval = self.deps.retrieve_material_context(
            self.course_id,
            f"{task.get('title', '')} {task.get('description', '')} 公式 定义 例题 习题 真题",
            limit=8,
        )
        lesson_evidence = retrieval.get("context", "") or self.evidence_context
        lesson_index = self.lesson_index_by_id.get(task_id, 0)
        previous_task = self.ordered_lessons[lesson_index - 1] if lesson_index > 0 else None
        next_task = self.ordered_lessons[lesson_index + 1] if lesson_index + 1 < len(self.ordered_lessons) else None
        previous_guide = previous_task.get("studyGuide", {}) if isinstance(previous_task, dict) else {}
        lesson_input = {
            "course": self.workspace.get("course", {}),
            "onboarding": {
                key: value for key, value in self.workspace.get("onboarding", {}).items()
                if key not in {"diagnosticScore", "diagnosticTotal", "diagnosticPercent", "diagnosticSubmittedAt"}
            },
            "contentStyle": self.style_contract,
            "strongFeedbackDirectives": self.strong_feedback_directives,
            "task": task,
            "knowledgePoint": self.point_by_id.get(str(task.get("knowledgePointId", "")), {}),
            "storyContinuity": {
                "previousLessonTitle": str(previous_task.get("title", "")) if isinstance(previous_task, dict) else "",
                "previousLessonHighlights": previous_guide.get("sourceHighlights", []) if isinstance(previous_guide, dict) else [],
                "previousStoryContext": previous_guide.get("storyContext", {}) if isinstance(previous_guide, dict) else {},
                "incomingQuestion": (previous_guide.get("storyContext", {}) or {}).get("outgoingQuestion", "") if isinstance(previous_guide, dict) else "",
                "nextLessonTitle": str(next_task.get("title", "")) if isinstance(next_task, dict) else "",
            },
            "evidence": lesson_evidence,
        }
        
        guide_artifact_type = f"lesson_guide_checkpoint:{task_id}"
        guide_signature = lesson_guide_signature(lesson_signature)
        
        def generate_guide(review_issues: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
            payload = lesson_input if not review_issues else {**lesson_input, "reviewIssues": review_issues}
            prompt = LESSON_CONTENT_PROMPT if not review_issues else LESSON_CONTENT_PROMPT + "\n请修复 reviewIssues 中的全部问题。"
            result = self.model_json(prompt, json.dumps(payload, ensure_ascii=False), self.course_prompt)
            self.check_cancelled()
            guide = result.get("studyGuide") if isinstance(result.get("studyGuide"), dict) else {}
            issues = _study_guide_issues(
                {**task, "_contentStyle": self.content_style, "studyGuide": guide},
                {},
                require_self_test=False,
            )
            issues.extend(_strong_feedback_issues(guide, self.strong_feedback_directives))
            return guide, list(dict.fromkeys(issues))
        
        cached_guide_artifact = self.deps.get_latest_artifact(self.course_id, guide_artifact_type)
        cached_guide_content = cached_guide_artifact.get("content", {}) if cached_guide_artifact else {}
        guide = cached_guide_content.get("studyGuide") if cached_guide_content.get("signature") == guide_signature else None
        guide_issues = (
            _study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": guide}, {}, require_self_test=False)
            if isinstance(guide, dict)
            else ["讲义检查点不可用"]
        )
        guide_from_backup = False
        if guide_issues:
            guide, guide_issues = generate_guide()
            if guide_issues:
                guide, guide_issues = generate_guide(guide_issues)
            if guide_issues:
                # 模型两次仍未产出合规讲义 → 确定性降级讲义兜底（同 _backup_mock_questions），
                # 保证学习单元始终有内容，而不是空着只打 contentQualityWarning。
                backup_guide = _backup_study_guide(task, lesson_input)
                backup_issues = _study_guide_issues(
                    {**task, "_contentStyle": self.content_style, "studyGuide": backup_guide}, {}, require_self_test=False
                )
                if backup_issues:
                    raise ValueError(
                        f"任务 {task_id} 讲义降级模板仍不合规：" + "；".join(backup_issues[:5])
                    )
                guide = backup_guide
                guide_from_backup = True
            else:
                self.deps.save_artifact(
                    self.course_id,
                    guide_artifact_type,
                    {"signature": guide_signature, "studyGuide": guide},
                    status="checkpoint",
                    source_run_id=self.run_id,
                )
        
        question_artifact_type = f"lesson_questions_checkpoint:{task_id}"
        question_signature = lesson_questions_signature(
            lesson_signature=lesson_signature,
            exam_points=guide.get("examPoints", []),
        )
        
        def generate_questions(review_issues: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
            practice_input = {
                "task": task,
                "examPoints": guide.get("examPoints", []),
                "workedExamples": guide.get("workedExamples", []),
            }
            if review_issues:
                practice_input["reviewIssues"] = review_issues
            prompt = LESSON_PRACTICE_PROMPT if not review_issues else LESSON_PRACTICE_PROMPT + "\n请修复 reviewIssues 中的全部问题。"
            result = self.model_json(prompt, json.dumps(practice_input, ensure_ascii=False), self.course_prompt)
            self.check_cancelled()
            questions = result.get("practiceQuestions") if isinstance(result.get("practiceQuestions"), list) else []
            questions = normalize_practice_questions(questions, guide)
            practice_by_id = {
                str(question.get("id")): question
                for question in questions
                if isinstance(question, dict) and question.get("id")
            }
            issues = _question_issues(questions, collection=f"任务 {task_id} 自测题")
            issues.extend(_study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": guide}, practice_by_id))
            return questions, list(dict.fromkeys(issues))
        
        cached_question_artifact = self.deps.get_latest_artifact(self.course_id, question_artifact_type)
        cached_question_content = cached_question_artifact.get("content", {}) if cached_question_artifact else {}
        questions = (
            cached_question_content.get("practiceQuestions")
            if cached_question_content.get("signature") == question_signature
            else None
        )
        question_issues: list[str] = []
        if isinstance(questions, list):
            questions = normalize_practice_questions(questions, guide)
            practice_by_id = {
                str(question.get("id")): question
                for question in questions
                if isinstance(question, dict) and question.get("id")
            }
            question_issues = _question_issues(questions, collection=f"任务 {task_id} 自测题")
            question_issues.extend(_study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": guide}, practice_by_id))
        else:
            question_issues = ["自测题检查点不可用"]
        questions_from_backup = False
        if question_issues:
            questions, question_issues = generate_questions()
            if question_issues:
                questions, question_issues = generate_questions(question_issues)
            if question_issues:
                # 模型两次仍未产出合规自测 → 降级题兜底（每考点一道单选），
                # 由 normalize_practice_questions 回填 selfTestQuestionIds，保证考点覆盖校验通过。
                backup_questions = normalize_practice_questions(_backup_practice_questions(task, guide), guide)
                backup_by_id = {
                    str(question.get("id")): question
                    for question in backup_questions
                    if isinstance(question, dict) and question.get("id")
                }
                backup_q_issues = _question_issues(backup_questions, collection=f"任务 {task_id} 自测题")
                backup_q_issues.extend(_study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": guide}, backup_by_id))
                if backup_q_issues:
                    raise ValueError(
                        f"任务 {task_id} 自测降级模板仍不合规：" + "；".join(backup_q_issues[:5])
                    )
                questions = backup_questions
                questions_from_backup = True
            else:
                self.deps.save_artifact(
                    self.course_id,
                    question_artifact_type,
                    {"signature": question_signature, "practiceQuestions": questions},
                    status="checkpoint",
                    source_run_id=self.run_id,
                )
        report = ReviewReport(
            passed=True,
            issues=[],
            source_coverage=1,
            summary="已通过来源、公式条件、例题完整性和自测覆盖校验。",
        )
        degraded = guide_from_backup or questions_from_backup
        attach_readability_review({**task, "studyGuide": guide}, self.content_style)
        # 降级内容不写入检查点，避免瞬时模型故障被永久缓存；下次生成会重新尝试模型。
        if not degraded:
            self.deps.save_artifact(
                self.course_id,
                artifact_type,
                {
                    "signature": lesson_signature,
                    "studyGuide": guide,
                    "practiceQuestions": questions,
                },
                status="checkpoint",
                source_run_id=self.run_id,
            )
        return task_id, guide, questions, report, degraded
        
