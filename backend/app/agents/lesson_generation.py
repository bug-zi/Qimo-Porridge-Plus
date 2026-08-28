from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .checkpoint_contracts import lesson_content_signature, lesson_guide_signature, lesson_questions_signature
from .content_patches import apply_guide_patches, apply_question_patches
from .content_prompts import (
    LESSON_CONTENT_PATCH_PROMPT,
    LESSON_CONTENT_PROMPT,
    LESSON_PRACTICE_PATCH_PROMPT,
    LESSON_PRACTICE_PROMPT,
)
from .content_validation import _study_guide_issues, split_guide_issues
from .contracts import ReviewReport
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
    publish_progress: Callable[[str, str, int], None] | None = None
    scoped_model_json: Callable[[str, str], JsonModelCall] | None = None
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
                # 缓存复用同样只看硬伤：只剩软伤（数量/顺序/措辞）的检查点视为可用。
                if not split_guide_issues(cached_issues)[0]:
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
        
        def generate_guide(review_issues: list[str] | None = None, attempt: int = 1) -> tuple[dict[str, Any], list[str]]:
            payload = lesson_input if not review_issues else {**lesson_input, "reviewIssues": review_issues}
            prompt = LESSON_CONTENT_PROMPT if not review_issues else LESSON_CONTENT_PROMPT + "\n请修复 reviewIssues 中的全部问题。"
            if self.publish_progress:
                self.publish_progress("lesson_guide", task_id, attempt)
            model_json = self.scoped_model_json("lesson_guide", task_id) if self.scoped_model_json else self.model_json
            result = model_json(prompt, json.dumps(payload, ensure_ascii=False), self.course_prompt)
            self.check_cancelled()
            guide = result.get("studyGuide") if isinstance(result.get("studyGuide"), dict) else {}
            issues = _study_guide_issues(
                {**task, "_contentStyle": self.content_style, "studyGuide": guide},
                {},
                require_self_test=False,
            )
            issues.extend(_strong_feedback_issues(guide, self.strong_feedback_directives))
            deduped_issues = list(dict.fromkeys(issues))
            if deduped_issues:
                # 失败原稿落盘：保留模型原始输出与触发它的校验问题，保证事后
                # 可以回放“模型到底写了什么、挂在哪条校验上”，而不是凭空丢弃
                # 数分钟的模型产出。每次尝试新增一个 version，不覆盖历史。
                try:
                    self.deps.save_artifact(
                        self.course_id,
                        f"lesson_guide_failed:{task_id}",
                        {
                            "attempt": attempt,
                            "stage": "repair" if review_issues else "initial",
                            "inputReviewIssues": review_issues or [],
                            "issues": deduped_issues,
                            "modelOutput": result,
                        },
                        status="failed",
                        source_run_id=self.run_id,
                    )
                except Exception:
                    # 落盘失败只损失可观测性，不影响生成主流程。
                    pass
            return guide, deduped_issues
        
        def patch_guide(base_guide: dict[str, Any], review_issues: list[str]) -> tuple[dict[str, Any], list[str]]:
            patch_input = {
                "task": task,
                "studyGuideDraft": base_guide,
                "reviewIssues": review_issues,
                "evidence": lesson_evidence,
            }
            if self.publish_progress:
                self.publish_progress("lesson_guide", task_id, 2)
            model_json = self.scoped_model_json("lesson_guide", task_id) if self.scoped_model_json else self.model_json
            result = model_json(LESSON_CONTENT_PATCH_PROMPT, json.dumps(patch_input, ensure_ascii=False), self.course_prompt)
            self.check_cancelled()
            patched = apply_guide_patches(base_guide, result)
            issues = _study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": patched}, {}, require_self_test=False)
            issues.extend(_strong_feedback_issues(patched, self.strong_feedback_directives))
            issues = list(dict.fromkeys(issues))
            self.deps.save_artifact(
                self.course_id,
                f"lesson_guide_patch:{task_id}",
                {"stage": "patch", "inputReviewIssues": review_issues, "patchOutput": result, "remainingIssues": issues},
                status="checkpoint" if not split_guide_issues(issues)[0] else "failed",
                source_run_id=self.run_id,
            )
            return patched, issues

        cached_guide_artifact = self.deps.get_latest_artifact(self.course_id, guide_artifact_type)
        cached_guide_content = cached_guide_artifact.get("content", {}) if cached_guide_artifact else {}
        guide = cached_guide_content.get("studyGuide") if cached_guide_content.get("signature") == guide_signature else None
        guide_issues = (
            _study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": guide}, {}, require_self_test=False)
            if isinstance(guide, dict)
            else ["讲义检查点不可用"]
        )
        soft_guide_issues: list[str] = []
        if guide_issues:
            guide, guide_issues = generate_guide(attempt=1)
            guide_blocking, soft_guide_issues = split_guide_issues(guide_issues)
            if guide_blocking:
                # 修复阶段只编辑初稿，不再重新生成完整 studyGuide。
                guide, guide_issues = patch_guide(guide, guide_blocking)
                guide_blocking, soft_guide_issues = split_guide_issues(guide_issues)
            if guide_blocking:
                raise ValueError(
                    f"任务 {task_id} 讲义初稿定向修复后仍有硬伤：" + "；".join(guide_blocking[:5])
                )
            else:
                self.deps.save_artifact(
                    self.course_id,
                    guide_artifact_type,
                    {"signature": guide_signature, "studyGuide": guide, "softIssues": soft_guide_issues},
                    status="checkpoint",
                    source_run_id=self.run_id,
                )
        
        question_artifact_type = f"lesson_questions_checkpoint:{task_id}"
        question_signature = lesson_questions_signature(
            lesson_signature=lesson_signature,
            exam_points=guide.get("examPoints", []),
        )
        
        def generate_questions(review_issues: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
            stage_attempt = 2 if review_issues else 1
            practice_input = {
                "task": task,
                "examPoints": guide.get("examPoints", []),
                "workedExamples": guide.get("workedExamples", []),
            }
            if review_issues:
                practice_input["reviewIssues"] = review_issues
            prompt = LESSON_PRACTICE_PROMPT if not review_issues else LESSON_PRACTICE_PROMPT + "\n请修复 reviewIssues 中的全部问题。"
            if self.publish_progress:
                self.publish_progress("lesson_questions", task_id, stage_attempt)
            model_json = self.scoped_model_json("lesson_questions", task_id) if self.scoped_model_json else self.model_json
            result = model_json(prompt, json.dumps(practice_input, ensure_ascii=False), self.course_prompt)
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
        questions_from_cache = isinstance(questions, list)
        if questions_from_cache:
            questions = normalize_practice_questions(questions, guide)
            practice_by_id = {
                str(question.get("id")): question
                for question in questions
                if isinstance(question, dict) and question.get("id")
            }
            question_issues = _question_issues(questions, collection=f"任务 {task_id} 自测题")
            question_issues.extend(_study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": guide}, practice_by_id))
        else:
            # 无有效检查点时必须先完整生成自测初稿（方案阶段三步骤1），
            # 不允许拿空初稿直接走 patch：patch 的 add_question 常不带
            # examPointIds，考点覆盖校验只认该字段，空稿进 patch 必然
            # 再次失败（现场：task-d3-03 六个考点全部"未被覆盖"）。
            questions, question_issues = generate_questions()
        # 与讲义同样的硬伤/软伤区分：故事数量/措辞类软伤不构成丢弃模型自测题的理由。
        question_blocking, soft_question_issues = split_guide_issues(question_issues)
        if question_blocking:
            # 先留档输入问题：下方 question_blocking 会被重新赋值为修复后剩余问题，
            # 直接引用会把"输入"存成"剩余"（现场 artifact 两者完全相同，误导诊断）。
            input_question_issues = list(question_blocking)
            patch_input = {
                "task": task,
                "studyGuide": guide,
                "practiceQuestionsDraft": questions if isinstance(questions, list) else [],
                "reviewIssues": question_blocking,
            }
            if self.publish_progress:
                self.publish_progress("lesson_questions", task_id, 2)
            model_json = self.scoped_model_json("lesson_questions", task_id) if self.scoped_model_json else self.model_json
            patch_result = model_json(LESSON_PRACTICE_PATCH_PROMPT, json.dumps(patch_input, ensure_ascii=False), self.course_prompt)
            self.check_cancelled()
            questions = apply_question_patches(questions if isinstance(questions, list) else [], patch_result, task_id)
            questions = normalize_practice_questions(questions, guide)
            practice_by_id = {str(question.get("id")): question for question in questions if isinstance(question, dict) and question.get("id")}
            question_issues = _question_issues(questions, collection=f"任务 {task_id} 自测题")
            question_issues.extend(_study_guide_issues({**task, "_contentStyle": self.content_style, "studyGuide": guide}, practice_by_id))
            question_blocking, soft_question_issues = split_guide_issues(list(dict.fromkeys(question_issues)))
            self.deps.save_artifact(
                self.course_id,
                f"lesson_questions_patch:{task_id}",
                {"stage": "patch", "inputReviewIssues": input_question_issues, "patchOutput": patch_result, "remainingIssues": question_issues},
                status="checkpoint" if not question_blocking else "failed",
                source_run_id=self.run_id,
            )
            if question_blocking:
                raise ValueError(
                    f"任务 {task_id} 自测初稿定向修复后仍有硬伤：" + "；".join(question_blocking[:5])
                )
        if not questions_from_cache:
            # 初稿一次通过或 patch 通过都要落盘检查点（原语义：仅缓存未命中路径保存），
            # 否则本节中断后重跑会重复整次自测生成。
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
        attach_readability_review({**task, "studyGuide": guide}, self.content_style)
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
        # 降级模式已按用户决策移除：能走到这里的一定是模型稿（软伤已接受并记录）。
        return task_id, guide, questions, report, False
        
