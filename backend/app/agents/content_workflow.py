from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .checkpoint_contracts import content_plan_signature, mock_questions_signature
from .content_prompts import CONTENT_PLANNER_PROMPT, MOCK_EXAM_PROMPT
from .contracts import ReviewReport
from .workflow_types import JsonModelCall
from .content_validation import (
    _deterministic_review,
    _plan_issues,
    _select_missing_lesson_tasks,
    _study_guide_issues,
)
from .lesson_generation import LessonBuilder, LessonRuntimeDeps
from .orientation import ORIENTATION_TASK_ID, _make_orientation_task, build_orientation_guide
from .readability_review import build_course_readability_review
from .question_generation import (
    _backup_mock_questions,
    _mock_blueprint_issues,
    _question_issues,
    _strong_feedback_issues,
    _shuffle_single_choice_options,
    _shuffle_single_choice_questions,
)
from ..agent_runtime import (
    AgentJobCancelled,
    create_agent_run,
    delete_artifacts_for_run,
    fail_agent_run,
    finish_agent_run,
    get_latest_artifact,
    record_agent_step,
    save_artifact,
)
from ..course_style_templates import course_style_prompt_context
from ..model_usage import model_call_scope
from ..knowledge_service import retrieve_material_context


def run_content_workflow(
    course_id: str,
    workspace: dict[str, Any],
    review_plan: str,
    course_prompt: str,
    evidence_context: str,
    model_json: JsonModelCall,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    repair_only: bool = False,
    lesson_limit: int | None = None,
    use_existing_plan: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    telemetry_job_id: str = "",
) -> dict[str, Any]:
    run_id = create_agent_run(course_id, "content_generation", {"revision": workspace.get("revision", 0)})
    expected_days = int(workspace.get("onboarding", {}).get("days", 1))
    daily_minutes = round(float(workspace.get("onboarding", {}).get("dailyHours", 1)) * 60)
    content_style = str(workspace.get("onboarding", {}).get("contentStyle") or "story")
    style_contract = course_style_prompt_context(content_style)
    strong_feedback_directives = [
        line.strip() for line in course_prompt.splitlines()
        if line.strip().startswith("MUST-")
    ]

    def check_cancelled() -> None:
        if should_cancel and should_cancel():
            raise AgentJobCancelled("用户已结束修复生成")

    def scoped_model_json(stage: str, task_id: str = "") -> JsonModelCall:
        def call(task_prompt: str, user_content: str, scoped_course_prompt: str = "") -> dict[str, Any]:
            with model_call_scope(job_id=telemetry_job_id, run_id=run_id, stage=stage, task_id=task_id):
                return model_json(task_prompt, user_content, scoped_course_prompt)
        return call

    planner_prompt = CONTENT_PLANNER_PROMPT
    mock_prompt = MOCK_EXAM_PROMPT
    try:
        generation_onboarding = {
            key: value for key, value in workspace.get("onboarding", {}).items()
            if key not in {"diagnosticScore", "diagnosticTotal", "diagnosticPercent", "diagnosticSubmittedAt"}
        }
        planner_input = {
            "course": workspace.get("course", {}),
            "onboarding": generation_onboarding,
            "assessmentProfile": workspace.get("assessmentProfile", {}),
            "reviewPlan": review_plan,
            "evidence": evidence_context,
        }
        plan_signature = content_plan_signature(
            course=workspace.get("course", {}),
            onboarding=generation_onboarding,
            review_plan=review_plan,
            course_prompt=course_prompt,
        )
        cached_plan = get_latest_artifact(course_id, "content_plan_checkpoint")
        cached_plan_content = cached_plan.get("content", {}) if cached_plan else {}
        if repair_only or use_existing_plan:
            # Incremental continuation and repair never replace the persisted plan, so rerunning the expensive
            # planner is both unnecessary and delays the first missing lesson by
            # several minutes. The current workspace is the authoritative plan.
            candidate = {
                "assessmentProfile": workspace.get("assessmentProfile", {}),
                "modules": workspace.get("modules", []),
                "knowledgePoints": workspace.get("knowledgePoints", []),
                "tasks": workspace.get("tasks", []),
            }
            planner_source = "workspace"
        elif cached_plan_content.get("signature") == plan_signature and isinstance(cached_plan_content.get("candidate"), dict):
            candidate = cached_plan_content["candidate"]
            planner_source = "checkpoint"
        else:
            candidate = model_json(planner_prompt, json.dumps(planner_input, ensure_ascii=False), course_prompt)
            planning_issues = _plan_issues(candidate, expected_days, daily_minutes)
            if planning_issues:
                candidate = model_json(
                    planner_prompt + "\n请修复 planningIssues 中的全部问题，仍只返回完整规划 JSON。",
                    json.dumps({**planner_input, "planningIssues": planning_issues}, ensure_ascii=False),
                    course_prompt,
                )
                planning_issues = _plan_issues(candidate, expected_days, daily_minutes)
            if planning_issues:
                raise ValueError("动态内容规划不完整：" + "；".join(planning_issues[:5]))
            save_artifact(
                course_id,
                "content_plan_checkpoint",
                {"signature": plan_signature, "candidate": candidate},
                status="checkpoint",
                source_run_id=run_id,
            )
            planner_source = "model"
        # 修复模式只补 studyGuide，不会也不应重排已经在使用中的任务。
        # 旧计划可能因学习进度重平衡形成某天不足/超预算；这属于调度问题，
        # 不能阻断内容补齐。结构、任务引用和来源等校验仍然保留。
        planning_issues = _plan_issues(
            candidate,
            expected_days,
            daily_minutes,
            validate_daily_budget=not (repair_only or use_existing_plan),
        )
        if planning_issues:
            raise ValueError("动态内容规划不完整：" + "；".join(planning_issues[:5]))

        if repair_only or use_existing_plan:
            # Existing task ids/order and learning progress remain authoritative. The
            # workflow receives the full plan, then selects only the next missing batch.
            existing_tasks = [dict(task) for task in workspace.get("tasks", []) if isinstance(task, dict)]
            candidate = {
                **candidate,
                "assessmentProfile": workspace.get("assessmentProfile", candidate.get("assessmentProfile", {})),
                "modules": workspace.get("modules", candidate.get("modules", [])),
                "knowledgePoints": workspace.get("knowledgePoints", candidate.get("knowledgePoints", [])),
                "tasks": existing_tasks,
            }
        record_agent_step(
            run_id,
            1,
            "content_planner",
            "completed",
            input_data={"reviewPlanCharacters": len(review_plan)},
            output_data={"taskCount": len(candidate.get("tasks", [])), "source": planner_source},
        )
        if on_progress and not (repair_only or use_existing_plan):
            on_progress(
                {
                    "stage": "content_plan",
                    "candidate": {
                        "assessmentProfile": candidate.get("assessmentProfile", {}),
                        "knowledgePoints": candidate.get("knowledgePoints", []),
                        "tasks": candidate.get("tasks", []),
                    },
                    "runId": run_id,
                }
            )

        tasks = [task for task in candidate.get("tasks", []) if isinstance(task, dict)]
        selected_tasks = _select_missing_lesson_tasks(tasks, lesson_limit)
        task_by_id = {str(task.get("id", "")): task for task in tasks if task.get("id")}
        point_by_id = {
            str(point.get("id")): point
            for point in candidate.get("knowledgePoints", [])
            if isinstance(point, dict) and point.get("id")
        }
        ordered_lessons = [
            item
            for item in sorted(tasks, key=lambda value: (int(value.get("day", 0)), int(value.get("order", 0))))
            if str(item.get("kind", "")) != "orientation"
        ]
        lesson_index_by_id = {str(item.get("id", "")): index for index, item in enumerate(ordered_lessons)}

        lesson_builder = LessonBuilder(
            course_id=course_id,
            workspace=workspace,
            review_plan=review_plan,
            course_prompt=course_prompt,
            evidence_context=evidence_context,
            model_json=scoped_model_json("lesson", ""),
            run_id=run_id,
            content_style=content_style,
            style_contract=style_contract,
            strong_feedback_directives=strong_feedback_directives,
            point_by_id=point_by_id,
            ordered_lessons=ordered_lessons,
            lesson_index_by_id=lesson_index_by_id,
            check_cancelled=check_cancelled,
            deps=LessonRuntimeDeps(
                get_latest_artifact=get_latest_artifact,
                save_artifact=save_artifact,
                retrieve_material_context=retrieve_material_context,
                shuffle_single_choice_options=_shuffle_single_choice_options,
            ),
        )

        def build_mock_questions() -> list[dict[str, Any]]:
            mock_signature = mock_questions_signature(
                onboarding=workspace.get("onboarding", {}),
                knowledge_points=candidate.get("knowledgePoints", []),
                task_plan=task_plan,
                review_plan=review_plan,
                course_prompt=course_prompt,
            )
            cached_mock = get_latest_artifact(course_id, "mock_questions_checkpoint")
            cached_mock_content = cached_mock.get("content", {}) if cached_mock else {}
            if cached_mock_content.get("signature") == mock_signature:
                cached_questions = cached_mock_content.get("mockQuestions")
                if isinstance(cached_questions, list):
                    cached_issues = _question_issues(cached_questions, collection="模拟题")
                    cached_issues.extend(
                        _mock_blueprint_issues(
                            cached_questions,
                            onboarding=workspace.get("onboarding", {}),
                            assessment_profile=candidate.get("assessmentProfile", {}),
                        )
                    )
                    if not cached_issues:
                        return cached_questions
            query = " ".join(str(point.get("name", "")) for point in candidate.get("knowledgePoints", []) if isinstance(point, dict))
            retrieval = retrieve_material_context(course_id, f"{query} 模拟卷 样卷 试卷 真题 考试题型 分值比例 综合题 计算题", limit=12)
            result = model_json(
                mock_prompt,
                json.dumps(
                    {
                        "course": workspace.get("course", {}),
                        "onboarding": workspace.get("onboarding", {}),
                        "assessmentProfile": candidate.get("assessmentProfile", {}),
                        "knowledgePoints": candidate.get("knowledgePoints", []),
                        "tasks": task_plan,
                        "evidence": retrieval.get("context", "") or evidence_context,
                    },
                    ensure_ascii=False,
                ),
                course_prompt,
            )
            questions = result.get("mockQuestions") if isinstance(result.get("mockQuestions"), list) else []
            issues = _question_issues(questions, collection="模拟题")
            issues.extend(
                _mock_blueprint_issues(
                    questions,
                    onboarding=workspace.get("onboarding", {}),
                    assessment_profile=candidate.get("assessmentProfile", {}),
                )
            )
            if issues:
                result = model_json(
                    mock_prompt + "\n请修复 questionIssues 中的全部问题。",
                    json.dumps(
                        {
                            "questionIssues": issues,
                            "course": workspace.get("course", {}),
                            "onboarding": workspace.get("onboarding", {}),
                            "assessmentProfile": candidate.get("assessmentProfile", {}),
                            "knowledgePoints": candidate.get("knowledgePoints", []),
                            "tasks": task_plan,
                            "evidence": retrieval.get("context", "") or evidence_context,
                        },
                        ensure_ascii=False,
                    ),
                    course_prompt,
                )
                questions = result.get("mockQuestions") if isinstance(result.get("mockQuestions"), list) else []
                issues = _question_issues(questions, collection="模拟题")
                issues.extend(
                    _mock_blueprint_issues(
                        questions,
                        onboarding=workspace.get("onboarding", {}),
                        assessment_profile=candidate.get("assessmentProfile", {}),
                    )
                )
            if issues:
                questions = _backup_mock_questions(workspace, candidate)
                backup_issues = _question_issues(questions, collection="模拟题")
                backup_issues.extend(
                    _mock_blueprint_issues(
                        questions,
                        onboarding=workspace.get("onboarding", {}),
                        assessment_profile=candidate.get("assessmentProfile", {}),
                    )
                )
                if backup_issues:
                    raise ValueError("模拟题生成不完整：" + "；".join((issues + backup_issues)[:5]))
                _shuffle_single_choice_questions(questions)
                save_artifact(
                    course_id,
                    "mock_questions_checkpoint",
                    {"signature": mock_signature, "mockQuestions": questions, "source": "recovered", "issues": issues},
                    status="checkpoint",
                    source_run_id=run_id,
                )
                return questions
            _shuffle_single_choice_questions(questions)
            save_artifact(
                course_id,
                "mock_questions_checkpoint",
                {"signature": mock_signature, "mockQuestions": questions},
                status="checkpoint",
                source_run_id=run_id,
            )
            return questions

        practice_questions: list[dict[str, Any]] = []
        lesson_reports: list[ReviewReport] = []
        task_plan = [{key: value for key, value in task.items() if key != "studyGuide"} for task in tasks]
        partial_errors: list[str] = []
        for task in selected_tasks:
            label = str(task.get("id", ""))
            try:
                task_id, guide, questions, report, degraded = lesson_builder.build(task)
            except AgentJobCancelled:
                delete_artifacts_for_run(
                    run_id,
                    [
                        f"lesson_content_checkpoint:{label}",
                        f"lesson_guide_checkpoint:{label}",
                        f"lesson_questions_checkpoint:{label}",
                    ],
                )
                raise
            except Exception as error:
                # 所有可用模型整体不可用（配额耗尽/连接失败）时立即中止整个生成任务，
                # 避免剩余几十节课逐节空转、每节都耗尽一遍重试预算。
                if "主模型与备用模型均不可用" in str(error) or "账户配额不足" in str(error):
                    raise ValueError(
                        f"任务 {label} 生成失败且当前无可用模型，已中止本轮生成：{error}"
                    ) from error
                partial_errors.append(f"任务 {label} 内容生成中断：{error}")
                task["contentQualityWarning"] = "讲义、例题和自测尚未完整生成；稍后可重新生成复习主线继续补齐。"
                record_agent_step(run_id, 3, f"lesson_builder:{label}", "failed", error=error)
                continue
            planned_task = task_by_id.get(task_id)
            if planned_task is not None:
                planned_task["studyGuide"] = guide
                if degraded:
                    planned_task["contentQualityWarning"] = (
                        "本节讲义/自测为降级模板（模型暂未产出完整内容）；可在资料更新后重新生成复习主线补齐。"
                    )
                else:
                    planned_task.pop("contentQualityWarning", None)
                if on_progress:
                    # 逐节增量回调：approve_strategy_documents 收到后立即把本节 studyGuide 写进
                    # workspace.json，前端轮询（每 1.8s）即可看到卡片从「内容生成中」翻成「开始学习」。
                    on_progress({
                        "stage": "lesson_built",
                        "task": planned_task,
                        "practiceQuestions": questions,
                        "runId": run_id,
                    })
            practice_questions.extend(questions)
            lesson_reports.append(report)
            record_agent_step(
                run_id,
                3,
                f"lesson_builder:{label}",
                "completed",
                output_data={"questionCount": len(questions), "review": report.model_dump()},
            )

        for task in tasks:
            if not isinstance(task.get("studyGuide"), dict):
                task["contentQualityWarning"] = str(
                    task.get("contentQualityWarning")
                    or "讲义、例题和自测仍在后台生成中；稍后可重新生成复习主线继续补齐。"
                )

        remaining_after_batch = [
            task for task in tasks
            if str(task.get("kind", "")) != "orientation" and not isinstance(task.get("studyGuide"), dict)
        ]
        content_complete = not remaining_after_batch
        if content_complete:
            try:
                candidate["mockQuestions"] = build_mock_questions()
                record_agent_step(
                    run_id,
                    2,
                    "exam_question_designer",
                    "completed",
                    output_data={"questionCount": len(candidate["mockQuestions"])},
                )
            except Exception as error:
                partial_errors.append(f"模拟题生成中断：{error}")
                candidate["mockQuestions"] = _backup_mock_questions(workspace, candidate)
                record_agent_step(run_id, 2, "exam_question_designer", "failed", error=error)
        else:
            candidate["mockQuestions"] = workspace.get("mockQuestions", [])

        candidate["tasks"] = tasks
        if repair_only or use_existing_plan:
            existing_questions = [question for question in workspace.get("practiceQuestions", []) if isinstance(question, dict)]
            existing_ids = {str(question.get("id")) for question in existing_questions}
            candidate["practiceQuestions"] = [*existing_questions, *[question for question in practice_questions if str(question.get("id")) not in existing_ids]]
        else:
            candidate["practiceQuestions"] = practice_questions
        remaining_after_batch = [
            task for task in tasks
            if str(task.get("kind", "")) != "orientation" and not isinstance(task.get("studyGuide"), dict)
        ]
        content_complete = not remaining_after_batch
        if partial_errors:
            report = ReviewReport(
                passed=False,
                issues=partial_errors,
                source_coverage=(
                    sum(item.source_coverage for item in lesson_reports) / len(lesson_reports)
                    if lesson_reports
                    else 0
                ),
                summary="复习主线任务骨架已生成；已完成的讲义和自测已保留，未完成内容可继续补齐。",
            )
            artifact_status = "partial"
        else:
            if content_complete:
                deterministic_issues = _deterministic_review(
                    candidate,
                    expected_days,
                    daily_minutes,
                    validate_daily_budget=not (repair_only or use_existing_plan),
                    content_style=content_style,
                )
                if deterministic_issues:
                    raise ValueError("分批内容合并后校验失败：" + "；".join(deterministic_issues[:5]))
            report = ReviewReport(
                passed=True,
                issues=[],
                source_coverage=(
                    sum(item.source_coverage for item in lesson_reports) / len(lesson_reports)
                    if lesson_reports
                    else 0
                ),
                summary=("全部学习单元已通过内容与覆盖审查。" if content_complete else f"本批已生成 {len(selected_tasks)} 课，还有 {len(remaining_after_batch)} 课待生成。"),
            )
            artifact_status = "approved"
        # 第0天·复习导引：校验通过后确定性注入（planner 契约不含 kind 字段，
        # 重复生成/修复生成靠 kind 判重保证幂等）。
        # 增量首批只生成选中的正式课程；复习导引属于整门课级内容，
        # 不应阻塞“生成第 1 课”。在生成剩余全部课程时再补齐。
        if lesson_limit is None and not any(isinstance(t, dict) and str(t.get("kind", "")) == "orientation" for t in tasks):
            orientation_guide, orientation_degraded = build_orientation_guide(
                scoped_model_json("orientation"),
                course_id=course_id,
                course=workspace.get("course", {}),
                onboarding=workspace.get("onboarding", {}),
                review_plan=review_plan,
                course_prompt=course_prompt,
                modules=candidate.get("modules", []),
                knowledge_points=candidate.get("knowledgePoints", []),
                tasks=tasks,
                assessment_profile=candidate.get("assessmentProfile", {}),
                run_id=run_id,
            )
            tasks.insert(0, _make_orientation_task(course_id, orientation_guide))
            candidate["tasks"] = tasks
            record_agent_step(
                run_id,
                4,
                "orientation_builder",
                "completed",
                output_data={"degraded": orientation_degraded},
            )
        candidate["readabilityReview"] = build_course_readability_review(tasks, content_style)
        save_artifact(course_id, "review_report", report.model_dump(), status=artifact_status, source_run_id=run_id)
        artifact = save_artifact(course_id, "content_bundle", candidate, status=artifact_status, source_run_id=run_id)
        finish_agent_run(run_id, {"artifact": artifact["id"], "partial": bool(partial_errors)})
        return {
            "candidate": candidate,
            "reviewReport": report.model_dump(),
            "runId": run_id,
            "completedLessonCount": len([task for task in tasks if str(task.get("kind", "")) != "orientation" and isinstance(task.get("studyGuide"), dict)]),
            "pendingLessonCount": len(remaining_after_batch),
            "requestedLessonLimit": lesson_limit,
            "contentComplete": content_complete,
        }
    except Exception as error:
        fail_agent_run(run_id, error)
        raise
