from __future__ import annotations

import base64
import json
import hashlib
import random
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .course_style_templates import normalize_course_content_style
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import ZipFile

from .agent_runtime import AgentJobCancelled, create_adjustment_proposal, enqueue_agent_job, has_agent_job_ownership, is_agent_job_cancelled, update_agent_job_progress
from .model_usage import model_call_scope, record_call_result, record_call_start
from .agents import ORIENTATION_TASK_ID, build_orientation_guide, run_content_workflow, run_strategy_workflow, with_structured_formula_rules
from .agents.answer_consistency import reconcile_question_answer
from .agents.tools import apply_operations_to_copy
from .agents.tutor import run_tutor_agent, run_tutor_agent_stream
from .agents.orientation import _make_orientation_task
from .agents.readability_review import build_course_readability_review
from .agents.question_generation import (
    _shuffle_single_choice_options,
    _shuffle_single_choice_questions,
    mock_questions_need_repair,
    repair_mock_questions,
)
from . import ocr_service
from . import study_scheduler
from .knowledge_service import (
    build_conversation_memory,
    get_knowledge_status,
    import_workspace_messages,
    latest_summarized_turn_id,
    learner_memory_context,
    record_chat_summary,
    record_chat_turn,
    record_learning_event,
    record_review_progress,
    retrieve_material_context,
    sync_material_documents,
    unsummarized_chat_turns,
    upsert_learner_memory,
)


from . import paths

# 路径常量已收敛到 paths.py（阶段2-1）；以下别名单纯为兼容旧 import/monkeypatch，
# 模块内部代码一律走 `paths.X` 属性访问，测试 patch paths 即全局生效。
DATA_DIRECTORY = paths.DATA_DIRECTORY
COURSES_DATA_DIRECTORY = paths.COURSES_DATA_DIRECTORY
RUNTIME_ENV_PATH = paths.RUNTIME_ENV_PATH
MATERIAL_CACHE_DIRECTORY = paths.MATERIAL_CACHE_DIRECTORY
_CONTENT_GENERATION_LOCKS_GUARD = threading.Lock()

# ------------------------------------------------------------------
# 模型调用层 re-export（实现已抽到 model_client.py，阶段1-1）
# 测试通过 patch.object(study_service, "_stream_model_turn") 等打桩，
# 因此这些符号必须绑定在本模块命名空间；不要在 study_service 里重定义。
# ------------------------------------------------------------------
from .model_client import (  # noqa: E402,F401
    BACKUP_MODEL_ENV_KEYS,
    MODEL_CONNECT_TIMEOUT_SECONDS,
    MODEL_MAX_ATTEMPTS,
    MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS,
    MODEL_REQUEST_TIMEOUT_SECONDS,
    MODEL_RETRYABLE_HTTP_CODES,
    MODEL_TRANSIENT_BACKOFF_BASE_SECONDS,
    MODEL_TRANSIENT_BACKOFF_CAP_SECONDS,
    MODEL_TRANSIENT_MAX_ATTEMPTS,
    MODEL_PROVIDER_BUDGET_SECONDS,
    PROVIDER_BREAKER_COOLDOWN_SECONDS,
    PROVIDER_BREAKER_THRESHOLD,
    RUNTIME_ENV_PATH as _MC_RUNTIME_ENV_PATH,
    _MODEL_USAGE,
    _MODEL_USAGE_RECENT,
    _MODEL_USAGE_LOCK,
    _PROVIDER_BREAKER,
    _extract_json,
    _model_agent_turn,
    _model_completion,
    _model_json,
    _model_providers,
    _note_provider_result,
    _non_retryable_http_reason,
    _open_model_stream,
    _provider_request,
    _read_backup_model_env,
    _read_runtime_env,
    _record_model_call_start,
    _record_model_usage,
    _request_model_json,
    _stream_model_turn,
    _transient_retry_delay,
    fetch_available_model_ids,
    get_backup_model_profile,
    get_model_usage,
    parse_available_model_ids,
    probe_model_chat,
    save_backup_model_profile,
    set_message_builder,
)


def _review_session_days(days: int, review_count: int) -> list[int]:
    """把「共复习 K 次」均匀落到「距考试 D 天」的日程上。

    与前端 web/src/utils/reviewSchedule.ts 严格一致，改这里必须同步改前端。

    - K <= 0 或缺省 → 按「每天」处理（等价于 1..D，向后兼容）。
    - K == 1 → [1]（只复习一次，放在第 1 天）。
    - K >= 2 → 第 j 次（j=0..K-1）落在 clamp(round(1 + j*(D-1)/(K-1)), 1, D)，去重保序。
    - K > D 时钳制为 D（一天最多一次复习）。
    """
    span = max(1, int(days))
    count = min(max(1, int(review_count)), span) if review_count and review_count > 0 else span
    if count == 1:
        return [1]
    seen: set[int] = set()
    result: list[int] = []
    for j in range(count):
        raw = 1 + (j * (span - 1)) / (count - 1)
        # 用 int(raw + 0.5) 而非 round()：Python round 是银行家舍入，JS Math.round 是四舍五入，
        # 两者在 .5 处会差一天（如 days=4,K=3）。前端 reviewSchedule.ts 用 Math.round，这里必须对齐。
        day = max(1, min(span, int(raw + 0.5)))
        if day not in seen:
            seen.add(day)
            result.append(day)
    return result


def _remap_tasks_to_review_sessions(tasks: list[dict[str, Any]], days: int, review_count: int) -> None:
    """把任务的 day 从「按内容顺序的 1..N」重映射到「共复习 K 次」的复习日上。

    仅当 0 < review_count < days 时启用（即用户显式调小复习频率）；其余情况（缺省/每天）
    保持原 day 不变，完全向后兼容。AI 仍按自然顺序产出任务，这里按出现顺序合并到 K 个
    复习日——重映射作为兜底，不依赖 AI 严格服从间隔指令。改这里需同步前端 reviewSchedule.ts。
    """
    if not tasks or days < 1 or not (0 < review_count < days):
        return
    session_days = _review_session_days(days, review_count)
    if not session_days:
        return
    # 导引任务（day=0）不参与收集与映射，否则 0 混入 ai_days 会让所有任务整体错位一格。
    session_tasks = [t for t in tasks if not study_scheduler.is_orientation(t)]
    ai_days = sorted({int(t["day"]) for t in session_tasks if isinstance(t.get("day"), int)})
    if not ai_days:
        return
    day_map = {
        ai_day: session_days[min(i, len(session_days) - 1)]
        for i, ai_day in enumerate(ai_days)
    }
    for task in session_tasks:
        task["day"] = day_map.get(int(task.get("day", 1)), session_days[0])


# ------------------------------------------------------------------
# 模型配置/用户画像域 re-export（实现已抽到 model_profiles.py，阶段2-1）。
# routers/settings.py 等外部消费方仍从 study_service 导入这些符号；
# 测试若需打桩请 patch model_profiles 本体。
# ------------------------------------------------------------------
from .model_profiles import (  # noqa: E402,F401
    MODEL_PROFILES_PATH,
    PLATFORM_SYSTEM_PROMPT,
    USER_PROFILE_PROMPT_MAX_LENGTH,
    USER_PROFILE_PROMPT_METADATA_KEY,
    _activate_model_profile_values,
    _ensure_app_metadata_table,
    _load_model_profile_store,
    _metadata_connection,
    _persist_model_profile_store,
    _rewrite_env_lines,
    _user_profile_metadata_key,
    build_model_messages,
    get_model_profiles,
    get_runtime_model_api_key,
    get_runtime_model_profile,
    get_user_profile_prompt,
    resolve_api_key_for_base_url,
    save_model_profile,
    save_runtime_model_profile,
    save_user_profile_prompt,
)


# ------------------------------------------------------------------
# 资料解析域 re-export（实现已抽到 material_parser.py，阶段2-2）。
# 外部消费方（routers/materials、agents/tools 等）与部分测试仍从
# study_service 导入这些符号；打桩请 patch material_parser 本体。
# ------------------------------------------------------------------
from .material_parser import (  # noqa: E402,F401
    DOCLING_SUFFIXES,
    IMAGE_SUFFIXES,
    MARKITDOWN_SUFFIXES,
    MATERIAL_ANALYSIS_VERSION,
    OFFICE_TO_PDF_SUFFIXES,
    SPREADSHEET_NAMESPACE,
    SPREADSHEET_RELATIONSHIP_NAMESPACE,
    PACKAGE_RELATIONSHIP_NAMESPACE,
    TEXT_SUFFIXES,
    XLSX_PREVIEW_MAX_ROWS,
    XLSX_PREVIEW_MAX_COLUMNS,
    _MARKITDOWN_CONVERTER,
    _MARKITDOWN_ERROR,
    _DOCLING_CONVERTER,
    _DOCLING_ERROR,
    _convert_file_to_pdf,
    _extract_image_with_vision,
    _extract_material_content,
    _extract_native_xlsx,
    _extract_pptx_excerpt,
    _extract_with_docling,
    _extract_with_markitdown,
    _extract_xlsx_preview,
    _find_soffice,
    _load_cached_parse,
    _material_cache_key,
    _material_cache_path,
    _normalize_extracted_text,
    _ocr_fallback_for_scanned_pdf,
    _read_xlsx_cell,
    _read_xlsx_shared_strings,
    _read_xlsx_sheet_paths,
    _relative_material_path,
    _save_cached_parse,
    _sheets_to_markdown,
    _xlsx_column_index,
    analyze_course_material,
    build_material_preview,
    resolve_converted_material_pdf_path,
    resolve_course_material_path,
)


# ------------------------------------------------------------------
# 资料管理域 re-export（实现已抽到 materials.py，阶段2-3）。
# 外部消费方（routers/materials、main.py、agents/tools、测试）仍从
# study_service 导入这些符号；打桩请 patch materials 本体。
# ------------------------------------------------------------------
from .materials import (  # noqa: E402,F401
    MAX_BATCH_MATERIAL_BYTES,
    MAX_SINGLE_MATERIAL_BYTES,
    MATERIAL_ROLE_PRIMARY,
    MATERIAL_ROLE_SUPPLEMENTARY,
    MATERIAL_ROLE_VALUES,
    _apply_material_roles,
    _build_material_memory,
    _mark_material_memory,
    _material_digest,
    _material_role_metadata,
    _normalize_material_role,
    _safe_upload_material_name,
    _workspace_needs_material_refresh,
    delete_course_material,
    refresh_workspace_materials,
    scan_course_materials,
    sync_course_knowledge,
    update_course_material_role,
    upload_course_material,
    upload_course_materials,
)

# ------------------------------------------------------------------
# 工作空间域 re-export（实现已抽到 workspace.py，阶段2-4）。
# 外部消费方（routers/courses、materials、course_feedback_service、tests）
# 仍从 study_service 导入这些符号。注意：load_workspace / save_workspace 的
# 历史打桩面在 study_service 命名空间（monkeypatch.setattr(study_service, ...)），
# workspace.py 内部经函数级延迟 import 读取本命名空间，旧打桩方式依旧生效。
# ------------------------------------------------------------------
from .workspace import (  # noqa: E402,F401
    WORKSPACE_CONTENT_VERSION,
    _CONTENT_GENERATION_LOCKS,
    _CONTENT_GENERATION_LOCKS_GUARD,
    _WORKSPACE_LOCKS,
    _WORKSPACE_LOCKS_GUARD,
    _atomic_write_text,
    _build_study_guide_sections,
    _clear_pre_plan_content,
    _complete_study_guide,
    _content_generation_lock,
    _course_data_directory,
    _course_material_directory,
    _course_overview_path,
    _empty_course_workspace,
    _ensure_workspace_content_quality,
    _mind_map_path,
    _reshuffle_unanswered_single_choice,
    _review_days_from_exam_date,
    _strategy_directory,
    _validate_course_id,
    _workspace_is_planned,
    _workspace_lock,
    _workspace_path,
    create_course_workspace,
    create_empty_course_workspace,
    load_mind_map,
    load_workspace,
    save_mind_map,
    save_workspace,
)


def _source_context(materials: list[dict[str, Any]], course_id: str) -> str:
    overview_path = _course_overview_path(course_id)
    overview = (
        overview_path.read_text(encoding="utf-8")
        if overview_path.exists()
        else "用户尚未提供人工整理的复习总览，请以资料库中的课件、练习题、真题和用户备注为准。"
    )
    catalogue = "\n".join(
        f"- {item['relativePath']}（{item['detail']}；{item.get('aiMessage', '')}）"
        for item in materials
    )
    parsed_excerpts = "\n\n".join(
        f"[{item['name']} | {item.get('parser', 'unknown')}]\n{item['excerpt']}"
        for item in materials
        if item.get("excerpt") and item.get("aiReadable")
    )
    unreadable_materials = "\n".join(
        f"- {item['relativePath']}：{item.get('aiMessage', '未进入 AI 解析上下文')}"
        for item in materials
        if not item.get("aiReadable")
    )
    return (
        "【已整理复习总览】\n"
        f"{overview[:24000]}\n\n"
        "【资料目录】\n"
        f"{catalogue[:8000]}\n\n"
        "【AI可读资料摘录】\n"
        f"{parsed_excerpts[:48000]}\n\n"
        "【未完整进入AI的资料】\n"
        f"{unreadable_materials[:5000]}"
    )


def _quiz_list_from_model(content: str) -> list[dict[str, Any]]:
    parsed = _extract_json(content)
    questions = parsed.get("questions")
    if not isinstance(questions, list):
        raise ValueError("模型未返回 questions")
    normalized: list[dict[str, Any]] = []
    for index, question in enumerate(questions[:8], start=1):
        if not isinstance(question, dict):
            continue
        options = question.get("options")
        answer_index = question.get("answerIndex")
        if not isinstance(options, list) or len(options) < 4:
            continue
        if not isinstance(answer_index, int) or answer_index < 0 or answer_index >= len(options):
            continue
        normalized.append(
            {
                "id": str(question.get("id") or f"diagnostic-{index:02d}"),
                "type": "single",
                "score": int(question.get("score", 5)),
                "prompt": str(question.get("prompt", "")).strip(),
                "options": [str(option) for option in options[:5]],
                "answerIndex": answer_index,
                "explanation": str(question.get("explanation", "")).strip(),
                "knowledgePointId": str(question.get("knowledgePointId") or "diagnostic"),
                "source": str(question.get("source") or "课程资料库"),
            }
        )
    if len(normalized) < 4:
        raise ValueError("模型返回的摸底题不足")
    _shuffle_single_choice_questions(normalized)
    return normalized


def _generate_diagnostic_questions(
    materials: list[dict[str, Any]],
    onboarding: dict[str, Any],
    course_id: str,
) -> list[dict[str, Any]]:
    context = _source_context(materials, course_id)
    prompt = with_structured_formula_rules("""
你是大学期末速成 Agent。请只根据用户上传资料和用户填写的考试信息，生成 6-8 道 10-15 分钟内可完成的摸底单选题。
目标：快速判断用户目前大概能考多少分、薄弱知识点在哪里，而不是正式模拟卷。
请仅返回 JSON 对象：
{
  "questions":[{"id":"英文短横线 id","type":"single","score":5,"prompt":"...","options":["...","...","...","..."],"answerIndex":0-3,"explanation":"...","knowledgePointId":"英文短横线知识点 id","source":"资料来源"}]
}
要求：题目覆盖课程核心考点、老师可能考察方式和资料中的高频练习/真题风格；正确答案要均匀分布在四个选项位置，不要固定放在 A 或某一处；解释写清关键判断依据。
""")
    user_profile = json.dumps(onboarding, ensure_ascii=False, indent=2)
    return _quiz_list_from_model(
        _model_completion(
            build_model_messages(
                prompt,
                f"【用户填写信息】\n{user_profile}\n\n{context}",
            ),
            json_mode=True,
        )
    )


def save_course_setup(
    setup: dict[str, Any],
    course_id: str,
) -> dict[str, Any]:
    workspace_path = _workspace_path(course_id)
    workspace = (
        load_workspace(course_id, refresh_materials=False)
        if workspace_path.exists()
        else _empty_course_workspace(
            [],
            course={
                "id": course_id,
                "name": str(setup["course_name"]),
                "examDate": str(setup.get("exam_date") or "待填写"),
                "targetScore": int(setup["target_score"]),
                "dailyHours": float(setup["daily_hours"]),
                "progress": 0,
                "color": "#3973e8",
                "icon": "book",
            },
        )
    )
    materials = scan_course_materials(course_id)
    if not materials:
        raise ValueError("请先在资料库导入至少一份复习资料")

    onboarding = {
        "status": "diagnostic",
        "courseName": setup["course_name"],
        "examDate": setup.get("exam_date", ""),
        "targetScore": setup["target_score"],
        "targetText": setup.get("target_text", ""),
        "dailyHours": setup["daily_hours"],
        "days": _review_days_from_exam_date(setup.get("exam_date")) or setup["days"],
        "reviewCount": int(setup.get("review_count") or 0) or setup["days"],
        "examFormat": setup.get("exam_format", ""),
        "remarks": setup.get("remarks", ""),
        "contentStyle": normalize_course_content_style(str(setup.get("content_style") or "story")),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    workspace["course"] = {
        **workspace.get("course", {}),
        "id": course_id,
        "name": onboarding["courseName"],
        "examDate": onboarding["examDate"] or "待填写",
        "targetScore": onboarding["targetScore"],
        "dailyHours": onboarding["dailyHours"],
        "progress": 0,
        "color": str(workspace.get("course", {}).get("color") or "#3973e8"),
        "icon": str(workspace.get("course", {}).get("icon") or "system"),
    }
    workspace["assessmentProfile"] = {
        "summary": "课程信息已保存，AI 将基于课程资料和你的复习目标初始化复习主线。",
        "questionTypes": [onboarding["examFormat"] or "待从资料和备注中判断"],
    }
    workspace["diagnostic"] = {
        "estimatedScore": "待摸底",
        "message": "已根据资料和你的目标生成摸底题。请先完成摸底，再初始化复习主线。",
    }
    workspace["onboarding"] = onboarding
    workspace["diagnosticQuestions"] = _generate_diagnostic_questions(materials, onboarding, course_id)
    workspace["knowledgePoints"] = []
    workspace["tasks"] = []
    workspace["practiceQuestions"] = []
    workspace["mockQuestions"] = []
    workspace["wrongAnswers"] = []
    _mark_material_memory(workspace, materials, change_note="课程信息已保存，摸底题已生成")
    workspace["generatedAt"] = datetime.now().isoformat(timespec="seconds")
    workspace["generationMode"] = "ai"
    save_workspace(workspace, course_id)
    return workspace


def update_course_plan_params(
    course_id: str,
    *,
    exam_date: str | None = None,
    days: int | None = None,
    daily_hours: float | None = None,
) -> dict[str, Any]:
    """只更新考试日期 / 复习天数 / 每日复习时间，绝不清空 tasks/studyGuide/practice。

    与 save_course_setup 的关键区别：不重置 onboarding.status、不重新生成摸底题、不动 tasks，
    因此 save_workspace 不会递增 planRevision。供「计划生成后动态调整参数」使用。
    """
    workspace = load_workspace(course_id, refresh_materials=False)
    onboarding = workspace.setdefault("onboarding", {})
    course = workspace.setdefault("course", {})

    if exam_date is not None:
        if not re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", str(exam_date).strip()):
            raise ValueError("考试日期格式应为 YYYY-MM-DD")
        course["examDate"] = exam_date
        onboarding["examDate"] = exam_date
    if daily_hours is not None:
        if not 0 < daily_hours <= 12:
            raise ValueError("每日复习时间必须在 0-12 小时之间")
        course["dailyHours"] = daily_hours
        onboarding["dailyHours"] = daily_hours
    if days is not None:
        if not 1 <= days <= 30:
            raise ValueError("复习天数必须在 1-30 之间")
        onboarding["days"] = days

    onboarding["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    save_workspace(workspace, course_id)
    return workspace

def _sanitize_custom_workspace(candidate: dict[str, Any], base: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
    workspace = {**base}
    course_id = str(base.get("course", {}).get("id"))
    for key in ("assessmentProfile", "knowledgePoints", "tasks", "practiceQuestions", "mockQuestions", "modules"):
        if candidate.get(key):
            workspace[key] = candidate[key]

    # 模块（章节/知识板块）层级清洗：去重、补 order、校验 moduleId 引用合法性。
    # 非法或缺失的 moduleId 一律剔除，留给 generate_mind_map 的 resolve_course_modules 兜底归并。
    raw_modules = workspace.get("modules") if isinstance(workspace.get("modules"), list) else []
    cleaned_modules: list[dict[str, Any]] = []
    module_ids: set[str] = set()
    for seq, module in enumerate(raw_modules, start=1):
        if not isinstance(module, dict):
            continue
        mid = str(module.get("id") or "").strip()
        if not mid or mid in module_ids:
            continue
        module_ids.add(mid)
        raw_order = module.get("order")
        order = int(raw_order) if isinstance(raw_order, (int, float)) and not isinstance(raw_order, bool) else seq
        cleaned_modules.append({
            "id": mid,
            "title": str(module.get("title") or mid).strip() or mid,
            "order": order,
        })

    points = [point for point in workspace.get("knowledgePoints", []) if isinstance(point, dict)]
    scheduling_warnings = study_scheduler.sanitize_dependencies(points)
    point_by_id = {str(point.get("id", "")): point for point in points}
    member_count: dict[str, int] = {mid: 0 for mid in module_ids}
    for point in points:
        declared_id = str(point.get("moduleId") or "").strip()
        if declared_id and declared_id in module_ids:
            member_count[declared_id] += 1
        elif "moduleId" in point:
            point["moduleId"] = ""
    # 丢弃没有知识点的空 module，避免画布出现空骨架节点。
    workspace["modules"] = [module for module in cleaned_modules if member_count.get(module["id"], 0) > 0]

    normalized_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(workspace.get("tasks", []), start=1):
        if not isinstance(task, dict):
            continue
        task["id"] = str(task.get("id") or f"task-{index}")
        task["courseId"] = course_id
        task["order"] = int(task.get("order", index))
        task["day"] = int(task.get("day", max(1, (index + 1) // 2)))
        task["duration"] = int(task.get("duration", 60))
        task["progress"] = 0
        task["status"] = "pending"
        task["priority"] = task.get("priority") if task.get("priority") in ("high", "medium", "low") else "medium"
        if not isinstance(task.get("studyGuide"), dict):
            task["contentQualityWarning"] = str(
                task.get("contentQualityWarning")
                or "讲义、例题和自测仍在后台生成中；稍后可重新生成复习主线继续补齐。"
            )
        normalized_tasks.append(task)
    onboarding_cfg = workspace.get("onboarding") or {}
    review_days = int(onboarding_cfg.get("days") or 0)
    review_count = int(onboarding_cfg.get("reviewCount") or 0)
    daily_minutes = round(float(onboarding_cfg.get("dailyHours") or 0) * 60) or 120
    if study_scheduler.has_dependencies(points):
        # 知识点带前置依赖：确定性调度器接管 day/order（拓扑序 + 按复习日时长装包）。
        scheduling_warnings.extend(
            study_scheduler.schedule_tasks(
                normalized_tasks,
                points,
                session_days=_review_session_days(review_days, review_count),
                daily_minutes=daily_minutes,
                modules=workspace.get("modules") if isinstance(workspace.get("modules"), list) else None,
            )
        )
    else:
        _remap_tasks_to_review_sessions(normalized_tasks, review_days, review_count)
    workspace["schedulingWarnings"] = scheduling_warnings
    workspace["tasks"] = normalized_tasks

    for question_key in ("practiceQuestions", "mockQuestions"):
        normalized_questions: list[dict[str, Any]] = []
        for index, question in enumerate(workspace.get(question_key, []), start=1):
            if not isinstance(question, dict):
                continue
            question_type = str(question.get("type", "single")).strip()
            is_written_mock = question_key == "mockQuestions" and question_type == "calculation"
            options = question.get("options")
            if is_written_mock:
                options = []
            elif not isinstance(options, list) or len(options) < 2:
                continue
            question["id"] = str(question.get("id") or f"{question_key}-{index}")
            question["type"] = "calculation" if is_written_mock else "single"
            if question_key == "mockQuestions":
                question["questionType"] = str(question.get("questionType") or "模拟题")
            question["score"] = int(question.get("score", 5 if question_key == "practiceQuestions" else 10))
            question["options"] = [str(option) for option in options]
            question["answerIndex"] = int(question.get("answerIndex", 0))
            if is_written_mock:
                question["referenceAnswer"] = str(question.get("referenceAnswer") or question.get("answer") or "")
                question["gradingRubric"] = [
                    str(item)
                    for item in question.get("gradingRubric", [])
                    if str(item).strip()
                ] if isinstance(question.get("gradingRubric"), list) else []
            question["knowledgePointId"] = str(question.get("knowledgePointId") or (points[0].get("id") if points else "diagnostic"))
            normalized_questions.append(question)
        workspace[question_key] = normalized_questions

    _mark_material_memory(workspace, materials, change_note="已根据课程资料和用户目标初始化复习主线")
    workspace["generatedAt"] = datetime.now().isoformat(timespec="seconds")
    workspace["generationMode"] = "ai"
    workspace["workspaceContentVersion"] = WORKSPACE_CONTENT_VERSION
    return workspace


def _merge_repaired_content(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Merge generated content into missing tasks without altering the persisted plan."""
    workspace = {**base}
    repaired_by_id = {
        str(task.get("id")): task
        for task in candidate.get("tasks", [])
        if isinstance(task, dict) and task.get("id")
    }
    merged_tasks: list[dict[str, Any]] = []
    for existing in base.get("tasks", []):
        if not isinstance(existing, dict):
            continue
        task = dict(existing)
        repaired = repaired_by_id.get(str(task.get("id", "")))
        if repaired and not isinstance(task.get("studyGuide"), dict) and isinstance(repaired.get("studyGuide"), dict):
            task["studyGuide"] = repaired["studyGuide"]
            if repaired.get("contentQualityWarning"):
                task["contentQualityWarning"] = repaired["contentQualityWarning"]
            else:
                task.pop("contentQualityWarning", None)
        merged_tasks.append(task)
    workspace["tasks"] = merged_tasks

    existing_questions = [question for question in base.get("practiceQuestions", []) if isinstance(question, dict)]
    existing_ids = {str(question.get("id")) for question in existing_questions}
    for question in candidate.get("practiceQuestions", []):
        if isinstance(question, dict) and str(question.get("id")) not in existing_ids:
            existing_questions.append(question)
            existing_ids.add(str(question.get("id")))
    workspace["practiceQuestions"] = existing_questions
    generated_mock = candidate.get("mockQuestions")
    if isinstance(generated_mock, list) and generated_mock:
        workspace["mockQuestions"] = generated_mock
    return workspace


def _write_content_plan_preview(
    course_id: str,
    candidate: dict[str, Any],
    base: dict[str, Any],
    run_id: str,
) -> None:
    workspace = load_workspace(course_id, refresh_materials=False)
    workspace["course"] = {**workspace.get("course", base.get("course", {})), "id": course_id}
    workspace["onboarding"] = {**workspace.get("onboarding", base.get("onboarding", {})), "status": "planned"}
    for key in ("assessmentProfile", "knowledgePoints", "modules"):
        if candidate.get(key):
            workspace[key] = candidate[key]
    normalized_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(candidate.get("tasks", []), start=1):
        if not isinstance(task, dict):
            continue
        normalized = {key: value for key, value in task.items() if key != "studyGuide"}
        normalized["id"] = str(normalized.get("id") or f"task-{index}")
        normalized["courseId"] = course_id
        normalized["order"] = int(normalized.get("order", index))
        normalized["day"] = int(normalized.get("day", max(1, (index + 1) // 2)))
        normalized["duration"] = int(normalized.get("duration", 60))
        normalized["progress"] = 0
        normalized["status"] = "pending"
        normalized["priority"] = normalized.get("priority") if normalized.get("priority") in ("high", "medium", "low") else "medium"
        normalized["contentQualityWarning"] = "讲义、例题和自测仍在后台生成中"
        normalized_tasks.append(normalized)
    onboarding_cfg = workspace.get("onboarding") or {}
    preview_points = [
        point
        for point in workspace.get("knowledgePoints", [])
        if isinstance(point, dict)
    ]
    preview_warnings = study_scheduler.sanitize_dependencies(preview_points)
    if study_scheduler.has_dependencies(preview_points) and normalized_tasks:
        # 骨架预览与最终清洗走同一调度器，保证预览期顺序 == 最终顺序。
        preview_warnings.extend(
            study_scheduler.schedule_tasks(
                normalized_tasks,
                preview_points,
                session_days=_review_session_days(
                    int(onboarding_cfg.get("days") or 0),
                    int(onboarding_cfg.get("reviewCount") or 0),
                ),
                daily_minutes=round(float(onboarding_cfg.get("dailyHours") or 0) * 60) or 120,
                modules=candidate.get("modules") if isinstance(candidate.get("modules"), list) else None,
            )
        )
    else:
        _remap_tasks_to_review_sessions(
            normalized_tasks,
            int(onboarding_cfg.get("days") or 0),
            int(onboarding_cfg.get("reviewCount") or 0),
        )
    workspace["schedulingWarnings"] = preview_warnings
    if normalized_tasks:
        workspace["tasks"] = normalized_tasks
    workspace["practiceQuestions"] = []
    workspace["mockQuestions"] = []
    strategy_documents = workspace.setdefault("strategyDocuments", {})
    strategy_documents["status"] = "approved"
    strategy_documents["maintenancePending"] = False
    strategy_documents["lastAgentRunId"] = run_id
    workspace["generationWarning"] = "复习主线任务骨架已生成，讲义、例题和练习仍在后台补齐。"
    save_workspace(workspace, course_id)


def _write_content_lesson_preview(
    course_id: str,
    task_id: str,
    task_with_guide: dict[str, Any],
    practice_questions: list[dict[str, Any]],
    run_id: str,
) -> None:
    """逐节增量落盘：把单节 studyGuide 写进 workspace.json，让前端轮询能实时看到卡片翻成「开始学习」。"""
    workspace = load_workspace(course_id, refresh_materials=False)
    updated = False
    for task in workspace.get("tasks", []):
        if str(task.get("id", "")) == task_id:
            guide = task_with_guide.get("studyGuide")
            if isinstance(guide, dict):
                task["studyGuide"] = guide
            warning = task_with_guide.get("contentQualityWarning")
            if warning:
                task["contentQualityWarning"] = str(warning)
            else:
                task.pop("contentQualityWarning", None)
            updated = True
            break
    if not updated:
        # 骨架预览尚未写入或 id 不匹配，跳过；最终 sanitize 会兜底。
        return
    existing_ids = {
        str(question.get("id"))
        for question in workspace.get("practiceQuestions", [])
        if isinstance(question, dict)
    }
    bucket = workspace.setdefault("practiceQuestions", [])
    for question in practice_questions:
        if isinstance(question, dict) and str(question.get("id")) not in existing_ids:
            bucket.append(question)
            existing_ids.add(str(question.get("id")))
    workspace.setdefault("strategyDocuments", {})["lastAgentRunId"] = run_id
    save_workspace(workspace, course_id)


def submit_course_diagnostic(
    answers: dict[str, int],
    course_id: str,
) -> dict[str, Any]:
    workspace = load_workspace(course_id, refresh_materials=False)
    questions = workspace.get("diagnosticQuestions", [])
    if not questions:
        raise KeyError("摸底题尚未生成")

    total = sum(int(question.get("score", 0)) for question in questions) or 1
    earned = 0
    wrong_topics: list[str] = []
    result_lines: list[str] = []

    def answer_label(question: dict[str, Any], answer_index: int) -> str:
        options = question.get("options")
        if not isinstance(options, list):
            options = []
        if answer_index < 0:
            return "未作答"
        if answer_index >= len(options):
            return "不会"
        return str(options[answer_index])

    for question in questions:
        reconcile_question_answer(question)
        selected = int(answers.get(question["id"], -1))
        answer_index = int(question.get("answerIndex", -1))
        correct = selected == answer_index
        selected_label = answer_label(question, selected)
        correct_label = answer_label(question, answer_index)
        if correct:
            earned += int(question.get("score", 0))
        else:
            wrong_topics.append(str(question.get("knowledgePointId", "未知知识点")))
        result_lines.append(
            f"- {question.get('prompt')}：{'正确' if correct else '错误'}；作答：{selected_label}；正确答案：{correct_label}；解析：{question.get('explanation', '')}"
        )

    diagnostic_percent = round(earned / total * 100)
    target_score = int(workspace.get("onboarding", {}).get("targetScore", 80))
    estimated_low = max(30, min(95, int(diagnostic_percent * 0.62 + 20)))
    estimated_high = min(99, estimated_low + 8)
    workspace["diagnostic"] = {
        "estimatedScore": f"{estimated_low}-{estimated_high} 分",
        "message": f"摸底得分 {earned}/{total}，目标 {target_score}+。本结果仅供你感受课程题目与当前作答状态，不参与复习策略或后续课程生成。",
    }
    workspace["onboarding"] = {
        **workspace.get("onboarding", {}),
        "status": "strategy-review",
        "diagnosticScore": earned,
        "diagnosticTotal": total,
        "diagnosticPercent": diagnostic_percent,
        "diagnosticSubmittedAt": datetime.now().isoformat(timespec="seconds"),
    }
    workspace["wrongAnswers"] = [
        item for item in workspace.get("wrongAnswers", [])
        if not (
            isinstance(item, dict)
            and (
                str(item.get("id", "")).startswith("diagnostic-")
                or str(item.get("questionType", "")) == "摸底测试"
            )
        )
    ]
    workspace["diagnosticAnswers"] = {str(key): int(value) for key, value in answers.items()}
    workspace["diagnosticResults"] = result_lines
    _clear_pre_plan_content(workspace)
    save_workspace(workspace, course_id)
    generate_strategy_documents(course_id)
    workspace = load_workspace(course_id, refresh_materials=False)
    return workspace


def _approve_strategy_documents_legacy(
    course_id: str,
    review_plan: str,
    course_prompt: str,
    *,
    expected_review_plan_version: int,
    expected_course_prompt_version: int,
) -> dict[str, Any]:
    save_strategy_documents(
        course_id,
        review_plan,
        course_prompt,
        expected_review_plan_version=expected_review_plan_version,
        expected_course_prompt_version=expected_course_prompt_version,
    )
    workspace = load_workspace(course_id, refresh_materials=False)
    materials = scan_course_materials(course_id)
    context = _source_context(materials, course_id)
    onboarding_json = json.dumps(workspace.get("onboarding", {}), ensure_ascii=False, indent=2)
    task_prompt = """
根据已确认的复习计划、课程总 Prompt、课程资料和用户目标，初始化完整复习工作台。摸底测试仅供用户体验题目，不得影响课程结构、内容深度、题量或练习安排。只能依据所给内容，不要编造不存在的章节。
请仅返回 JSON 对象：
{
  "assessmentProfile":{"summary":"...","questionTypes":["..."]},
  "modules":[{"id":"英文短横线 id","title":"按学科主题命名的标准模块（应来自当前课程资料或教学大纲），禁止照搬资料文件名或资料自带章节","order":1}],
  "knowledgePoints":[{"id":"英文短横线 id","name":"...","mastery":0-100,"weight":1-30,"difficulty":1-5,"prerequisites":["其他知识点id，仅当存在真实学习先后依赖时才填，禁止填自身、编造id或形成环"],"summary":"用简短一两句话描述该知识点的关键知识，不要罗列资料出处","source":"...","moduleId":"必须命中 modules 中的某个 id"}],
  "tasks":[{"id":"英文短横线 id","courseId":"课程 id","day":1-14,"order":1,"title":"...","description":"...","source":"内部依据，不在界面展示","duration":整数分钟,"progress":0,"weight":1-30,"knowledgePointId":"...","status":"pending","priority":"high|medium|low","studyGuide":{"objectives":["..."],"concepts":[{"title":"...","body":"...","formula":"..."}],"example":{"title":"...","setup":"...","steps":["..."],"conclusion":"..."},"checklist":["..."]}}],
  "practiceQuestions":[{"id":"英文短横线 id","type":"single","score":5,"prompt":"...","options":["...","...","...","..."],"answerIndex":0-3,"explanation":"...","knowledgePointId":"...","source":"..."}],
  "mockQuestions":[{"id":"英文短横线 id","type":"single","questionType":"单项选择题","score":5-15,"prompt":"...","options":["...","...","...","..."],"answerIndex":0-3,"explanation":"...","knowledgePointId":"...","source":"..."},{"id":"英文短横线 id","type":"calculation","questionType":"计算题","score":10-30,"prompt":"完整计算题题干","referenceAnswer":"参考答案和关键计算过程","gradingRubric":["评分点"],"explanation":"详细解析","knowledgePointId":"...","source":"..."}]
}
规则：任务覆盖用户填写的复习天数和每日时间；练习依据课程资料、考试要求和已确认复习计划安排；模拟卷必须先仿照上传资料中的模拟卷/样卷/真题结构，没有样卷时再按用户填写的考试形式和备注编排题型、题量与分值比例，例如“选择30分计算题70分”就按 30/70 组织；计算题、综合题、简答题必须返回 type="calculation" 且包含 referenceAnswer 和 gradingRubric，不能压成选择题；任务内容必须服从已确认复习计划。source 字段仅作为内部元数据，标题、描述、讲义、例题、自测解析等用户可见内容不要写“来源、出处、资料依据、参考”。
modules 代表课程的几大知识模块（通常 4-8 个），必须按这门课在教科书/教学大纲中的标准章节主题划分（如操作系统 → 内存管理/进程管理/文件系统管理/输入输出设备管理；物理学 → 力学/热学/电磁学/光学）：每个标准章节独立成模块，模块内再拆小节知识点；不要把「基础概念」「综合应用」这类学习阶段当模块，也不要把多个标准章节拼成混合模块（如「I/O 与文件系统」应拆成「文件系统管理」「输入输出设备管理」两章）；模块顺序遵循教材标准讲授主线，「跨章节综合/冲刺」类内容可保留为最末一个模块；用户指定过模块划分或顺序时以用户为准。上传资料仅作学习素材，严禁把资料文件名或资料自带的章节划分直接搬进 modules，也不得把每个知识点各列一章。每个 knowledgePoint 必须通过 moduleId 归到且仅归到一个 module，moduleId 必须命中 modules 中已声明的某个 id。
knowledgePoints 的 difficulty 表示学习难度（1 最简单、5 最难，依据资料的抽象程度和计算复杂度判断）；prerequisites 只填真实存在的学习先后依赖（如先学习基础定义，再学习依赖它的综合应用），无依赖就不要填；tasks 的 day 与 order 仍按每日时间预算正常编排，系统会基于依赖关系统一重排复习顺序。
"""
    try:
        candidate = _extract_json(
            _model_completion(
                build_model_messages(
                    task_prompt,
                    (
                        f"【用户设置】\n{onboarding_json}"
                        f"\n\n【已确认复习计划】\n{review_plan}\n\n{context}"
                    ),
                    course_prompt=course_prompt,
                ),
                json_mode=True,
            )
        )
        workspace = _sanitize_custom_workspace(candidate, workspace, materials)
    except Exception as error:
        workspace["generationWarning"] = str(error)
        save_workspace(workspace, course_id)
        raise RuntimeError(f"复习主线生成失败：{error}") from error

    workspace["course"] = {**workspace.get("course", {}), "id": course_id}
    workspace["onboarding"] = {**workspace.get("onboarding", {}), "status": "planned"}
    workspace.setdefault("strategyDocuments", {})["status"] = "approved"
    workspace["strategyDocuments"]["maintenancePending"] = False
    save_workspace(workspace, course_id)
    return workspace


def approve_strategy_documents(
    course_id: str,
    review_plan: str,
    course_prompt: str,
    *,
    expected_review_plan_version: int,
    expected_course_prompt_version: int,
    repair_only: bool = False,
    generation_mode: str = "all",
    lesson_limit: int | None = None,
    continue_generation: bool = False,
    wait_for_generation_lock: bool = False,
    job_id: str = "",
    lease_token: str = "",
) -> dict[str, Any]:
    """Generate the mainline, or fill only missing lesson content in repair mode.

    repair_only is deliberately non-destructive: the existing task plan, stable task
    ids, progress fields, study guides, question history, and plan start date remain
    authoritative. Only tasks without a studyGuide are sent through generation.

    Background jobs may wait for another content generator (for example an automatic
    mock-paper repair) to release the per-course lock. Interactive legacy calls still
    fail fast, so an accidental duplicate HTTP request cannot occupy a request worker.
    """
    if generation_mode not in {"incremental", "all"}:
        raise ValueError("不支持的内容生成模式")
    if lesson_limit is not None and (isinstance(lesson_limit, bool) or lesson_limit < 1):
        raise ValueError("每批生成课数必须大于等于 1")
    if generation_mode == "all":
        lesson_limit = None

    generation_lock = _content_generation_lock(course_id)
    lock_acquired = (
        generation_lock.acquire(timeout=30 * 60)
        if wait_for_generation_lock
        else generation_lock.acquire(blocking=False)
    )
    if not lock_acquired:
        raise RuntimeError("当前课程已有内容生成任务正在运行，请稍后重试。")
    try:
        if repair_only or continue_generation:
            # 修复和继续生成只消费已经批准的文档，不应再次写入并提升版本。
            # 否则一次中途失败就会让后台任务携带的版本立即过期，后续点击修复
            # 只能得到“复习计划已被更新”，无法继续复用课程检查点。
            workspace = load_workspace(course_id, refresh_materials=False)
            strategy_documents = workspace.get("strategyDocuments", {})
            if int(strategy_documents.get("reviewPlan", {}).get("version", 0)) != expected_review_plan_version:
                raise RuntimeError("复习计划已被更新，请刷新后重试")
            if int(strategy_documents.get("coursePrompt", {}).get("version", 0)) != expected_course_prompt_version:
                raise RuntimeError("课程总 Prompt 已被更新，请刷新后重试")
            _validate_strategy_content("reviewPlan", review_plan)
            _validate_strategy_content("coursePrompt", course_prompt)
        else:
            save_strategy_documents(
                course_id,
                review_plan,
                course_prompt,
                expected_review_plan_version=expected_review_plan_version,
                expected_course_prompt_version=expected_course_prompt_version,
            )
            workspace = load_workspace(course_id, refresh_materials=False)
        materials = scan_course_materials(course_id)
        try:
            def publish_job_progress(stage: str, task_id: str = "", stage_attempt: int = 0) -> None:
                if not job_id:
                    return
                try:
                    update_agent_job_progress(
                        job_id,
                        {"stage": stage, "taskId": task_id, "stageAttempt": stage_attempt},
                        lease_token=lease_token,
                    )
                except sqlite3.Error:
                    # 可观察性写入失败不能反向中断课程生成；下一次阶段或 lease 心跳仍会更新。
                    pass

            publish_job_progress("preparing")
            sync_course_knowledge(course_id, workspace)
            retrieval = retrieve_material_context(
                course_id,
                f"{workspace.get('course', {}).get('name', '')} 复习计划 知识点 公式 题型 例题 真题",
                limit=20,
            )
            evidence_context = retrieval.get("context", "") or _source_context(materials, course_id)
            def publish_content_progress(update: dict[str, Any]) -> None:
                if job_id and (is_agent_job_cancelled(job_id) or (
                    lease_token and not has_agent_job_ownership(job_id, lease_token)
                )):
                    raise AgentJobCancelled("课程生成任务已停止或失去执行权")
                stage = update.get("stage")
                if stage == "content_plan" and isinstance(update.get("candidate"), dict):
                    _write_content_plan_preview(course_id, update["candidate"], workspace, str(update.get("runId", "")))
                elif stage == "lesson_built" and isinstance(update.get("task"), dict):
                    _write_content_lesson_preview(
                        course_id,
                        str(update["task"].get("id", "")),
                        update["task"],
                        update.get("practiceQuestions") or [],
                        str(update.get("runId", "")),
                    )

            from .course_feedback_service import append_course_feedback_rules

            effective_course_prompt = append_course_feedback_rules(course_id, course_prompt)
            result = run_content_workflow(
                course_id,
                workspace,
                review_plan,
                effective_course_prompt,
                evidence_context,
                _model_json,
                on_progress=publish_content_progress,
                repair_only=repair_only,
                lesson_limit=lesson_limit,
                use_existing_plan=repair_only or continue_generation,
                should_cancel=(
                    (lambda: is_agent_job_cancelled(job_id) or (
                        lease_token and not has_agent_job_ownership(job_id, lease_token)
                    ))
                    if job_id
                    else None
                ),
                telemetry_job_id=job_id,
                publish_job_progress=publish_job_progress,
            )
            if job_id and (is_agent_job_cancelled(job_id) or (
                lease_token and not has_agent_job_ownership(job_id, lease_token)
            )):
                raise AgentJobCancelled("课程生成任务已停止或失去执行权")
            publish_job_progress("finalizing")
            if repair_only or continue_generation:
                # Incremental generation can run while the learner keeps studying.
                # Merge into the newest persisted workspace so progress recorded
                # during generation is never overwritten by the stale start copy.
                latest_workspace = load_workspace(course_id, refresh_materials=False)
                workspace = _merge_repaired_content(latest_workspace, result["candidate"])
            else:
                workspace = _sanitize_custom_workspace(result["candidate"], workspace, materials)
        except AgentJobCancelled:
            # 已完整发布的上一节保留；当前模型响应及其半成品检查点由 workflow 丢弃。
            # 用户主动结束不是生成故障，不污染 maintenanceError/generationWarning。
            raise
        except Exception as error:
            workspace = load_workspace(course_id, refresh_materials=False)
            workspace["generationWarning"] = str(error)
            strategy_documents = workspace.setdefault("strategyDocuments", {})
            if not (repair_only or continue_generation):
                workspace["onboarding"] = {**workspace.get("onboarding", {}), "status": "strategy-review"}
                strategy_documents["status"] = "review"
            strategy_documents["maintenanceError"] = str(error)
            save_workspace(workspace, course_id)
            raise RuntimeError(f"多 Agent 复习主线生成失败：{error}") from error

        workspace["course"] = {**workspace.get("course", {}), "id": course_id}
        workspace["onboarding"] = {**workspace.get("onboarding", {}), "status": "planned"}
        workspace["readabilityReview"] = build_course_readability_review(
            [task for task in workspace.get("tasks", []) if isinstance(task, dict)],
            str(workspace.get("onboarding", {}).get("contentStyle") or "standard"),
        )
        if not (repair_only or continue_generation) or not workspace.get("planStartDate"):
            workspace["planStartDate"] = datetime.now().date().isoformat()
        strategy_documents = workspace.setdefault("strategyDocuments", {})
        strategy_documents["status"] = "approved"
        strategy_documents["maintenancePending"] = False
        strategy_documents["maintenanceError"] = ""
        strategy_documents["lastAgentRunId"] = result["runId"]
        strategy_documents["reviewReport"] = result["reviewReport"]
        pending_count = int(result.get("pendingLessonCount", 0))
        workspace["generationWarning"] = (f"还有 {pending_count} 课待生成。" if pending_count else "")
        save_workspace(workspace, course_id)
        # 全部课程完成后再刷新术语，避免逐课模式每批重复入队。
        if pending_count == 0:
            try:
                enqueue_agent_job(course_id, "glossary_refresh", {"event": "复习主线生成完成"}, max_attempts=2)
            except Exception:
                pass  # 术语刷新失败不影响主线生成结果
        return workspace
    finally:
        generation_lock.release()


def review_course_readability(course_id: str) -> dict[str, Any]:
    """Re-audit generated lessons without changing teaching facts or answers."""
    generation_lock = _content_generation_lock(course_id)
    if not generation_lock.acquire(blocking=False):
        raise RuntimeError("当前课程仍在生成内容，请等待生成结束后再审核排版。")
    try:
        with _workspace_lock(course_id):
            workspace = load_workspace(course_id, refresh_materials=False)
            workspace["readabilityReview"] = build_course_readability_review(
                [task for task in workspace.get("tasks", []) if isinstance(task, dict)],
                str(workspace.get("onboarding", {}).get("contentStyle") or "standard"),
            )
            save_workspace(workspace, course_id)
            return workspace
    finally:
        generation_lock.release()


def run_glossary_refresh_job(course_id: str, event: str = "", *, force: bool = False) -> dict[str, Any]:
    """glossary_refresh 后台 job 入口：加载 workspace 并执行术语刷新。"""
    from .agents.glossary import run_glossary_refresh

    workspace = load_workspace(course_id, refresh_materials=False)
    return run_glossary_refresh(course_id, workspace, _model_json, event=event, force=force)


def ensure_orientation_task(course_id: str, *, force: bool = False) -> dict[str, Any]:
    """为已有课程补生成第0天·复习导引任务（幂等；force=True 时重新生成）。"""
    workspace = load_workspace(course_id, refresh_materials=False)
    tasks = [t for t in workspace.get("tasks", []) if isinstance(t, dict)]
    existing = [t for t in tasks if study_scheduler.is_orientation(t)]
    if existing and not force:
        return workspace

    guide, degraded = build_orientation_guide(
        _model_json,
        course_id=course_id,
        course=workspace.get("course", {}),
        onboarding=workspace.get("onboarding", {}),
        review_plan=_read_strategy_document(course_id, "reviewPlan"),
        course_prompt=get_course_prompt(course_id),
        modules=workspace.get("modules", []),
        knowledge_points=workspace.get("knowledgePoints", []),
        tasks=[t for t in tasks if not study_scheduler.is_orientation(t)],
        assessment_profile=workspace.get("assessmentProfile", {}),
    )
    orientation_task = _make_orientation_task(course_id, guide)
    if existing:
        # 强制重建只换导引内容；已读/完成状态沿用旧任务，避免主线重排后把
        # 用户已完成的导引打回未读（progress 统计会随之回退）。
        previous = existing[0]
        for key in ("status", "progress", "completedAt"):
            if previous.get(key) is not None:
                orientation_task[key] = previous[key]
    workspace["tasks"] = [orientation_task] + [t for t in tasks if not study_scheduler.is_orientation(t)]
    save_workspace(workspace, course_id)
    return workspace


# ------------------------------------------------------------------
# 策略文档域 re-export（实现已抽到 strategy.py，阶段2-8）。
# 打桩面说明：strategy.py 的 load_workspace / save_workspace /
# _strategy_directory / _atomic_write_text / _source_context /
# scan_course_materials / sync_course_knowledge / retrieve_material_context /
# build_model_messages / get_user_profile_prompt / _extract_json /
# _model_completion / _model_json / _stream_model_turn / _sse 均在函数
# 体内延迟 import 本模块，monkeypatch study_service 命名空间依旧生效。
# ------------------------------------------------------------------
from .strategy import (  # noqa: E402,F401
    COURSE_PROMPT_DELIMITER,
    REPLY_DELIMITER,
    REVIEW_PLAN_DELIMITER,
    STRATEGY_REVISION_TASK_PROMPT,
    _generate_strategy_documents_legacy,
    _read_strategy_document,
    _split_revision_output,
    _strategy_document_paths,
    _validate_strategy_content,
    _write_strategy_document,
    generate_strategy_documents,
    get_course_prompt,
    get_strategy_documents,
    mark_strategy_maintenance_pending,
    revise_strategy_draft,
    save_strategy_documents,
    update_course_prompt,
)


def _knowledge_point_pid(point: dict[str, Any], index: int) -> str:
    """知识点在模块归并中的稳定标识。generate_mind_map 必须用完全相同的逻辑，
    否则 resolve_course_modules 返回的 point_id 映射会对不上。"""
    return str(point.get("id") or "").strip() or f"kp-{index}"


def _slugify_module_id(text: str) -> str:
    raw = re.sub(r"[^一-龥A-Za-z0-9]+", "-", str(text or "")).strip("-").lower()
    digest = hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:8]
    return f"mod-{raw[:40] or 'chapter'}-{digest}"


def _cluster_points_by_name(points: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """对没有章节信号的知识点，按名称中文 2-gram 共现做轻量聚类（并查集）。
    返回 [(cluster_title, members)]；超过 8 组时把最小的若干组合并进「综合知识」。"""
    if not points:
        return []

    parent = {id(p): id(p) for p in points}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def bigrams(name: str) -> set[str]:
        clean = re.sub(r"[^一-龥]+", "", name)
        return {clean[i:i + 2] for i in range(len(clean) - 1)} if len(clean) >= 2 else (set() if not clean else {clean})

    point_grams = [(p, bigrams(str(p.get("name", "")))) for p in points]
    for i in range(len(point_grams)):
        for j in range(i + 1, len(point_grams)):
            if point_grams[i][1] & point_grams[j][1]:
                union(id(point_grams[i][0]), id(point_grams[j][0]))

    grouped: dict[int, list[dict[str, Any]]] = {}
    for point, _ in point_grams:
        grouped.setdefault(find(id(point)), []).append(point)

    items = [sorted(members, key=lambda p: len(str(p.get("name", "")))) for members in grouped.values()]
    items.sort(key=lambda members: len(members), reverse=True)
    result = [(str(members[0].get("name", "综合知识")).strip()[:12] or "综合知识", members) for members in items]
    if len(result) > 8:
        kept = result[:7]
        rest = [p for _, members in result[7:] for p in members]
        if rest:
            kept.append(("综合知识", rest))
        result = kept
    return result


def resolve_course_modules(workspace: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """推导课程的「模块」层级。返回 (modules, point_id -> module_id)。

    模块只来自两个来源——绝不再从资料文件名或 source 抽章号（资料只是学习素材）：
      ① knowledgePoint.moduleId 已声明且命中 workspace.modules → 直接用（新课程 AI 产出）
      ② 其余知识点 → 按名称 2-gram 共现聚类兜底（老课程自动重算，即时可用）
    声明模块保留原 id 与 order；聚类模块 id 用 slug+digest 稳定化以便继承用户拖拽坐标。
    """
    points = [point for point in workspace.get("knowledgePoints", []) if isinstance(point, dict)]

    declared: dict[str, dict[str, Any]] = {}
    declared_seq: list[str] = []
    for module in workspace.get("modules") or []:
        if not isinstance(module, dict):
            continue
        mid = str(module.get("id") or "").strip()
        if not mid:
            continue
        declared[mid] = {"title": str(module.get("title") or mid).strip(), "order": module.get("order")}
        declared_seq.append(mid)

    buckets: dict[str, dict[str, Any]] = {}

    def assign(token: str, *, order: Any, title: str, pid: str, module_id: str | None = None) -> None:
        if token not in buckets:
            buckets[token] = {"order": order, "title": title, "point_ids": [], "module_id": module_id}
        if pid not in buckets[token]["point_ids"]:
            buckets[token]["point_ids"].append(pid)

    pending_points: list[dict[str, Any]] = []
    pending_pid: dict[int, str] = {}
    for index, point in enumerate(points):
        pid = _knowledge_point_pid(point, index)

        declared_id = str(point.get("moduleId") or "").strip()
        if declared_id and declared_id in declared:
            spec = declared[declared_id]
            order = spec["order"] if isinstance(spec.get("order"), int) else (declared_seq.index(declared_id) + 1)
            assign(f"declared:{declared_id}", order=order, title=spec["title"], pid=pid, module_id=declared_id)
            continue

        pending_points.append(point)
        pending_pid[id(point)] = pid

    for seq, (title, members) in enumerate(_cluster_points_by_name(pending_points), start=100):
        for member in members:
            assign(f"cluster:{title}", order=seq, title=title, pid=pending_pid[id(member)])

    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, int]:
        order = item[1].get("order")
        return (0, order) if isinstance(order, int) else (1, 0)

    modules: list[dict[str, Any]] = []
    point_to_module: dict[str, str] = {}
    for fallback_seq, (token, data) in enumerate(sorted(buckets.items(), key=sort_key), start=1):
        title = str(data.get("title") or "课程知识点").strip() or "课程知识点"
        module_id = data.get("module_id") or _slugify_module_id(title)
        order = data["order"] if isinstance(data.get("order"), int) else fallback_seq
        modules.append({"id": module_id, "title": title, "order": order})
        for pid in data["point_ids"]:
            point_to_module[pid] = module_id

    return modules, point_to_module


def _llm_regroup_modules(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """调 LLM 对知识点做语义聚类，返回 (modules, point_id -> module_id)。
    模型未配置或返回不合法时抛异常，由调用方回退到确定性聚类。"""
    catalog_lines: list[str] = []
    for index, point in enumerate(points):
        pid = _knowledge_point_pid(point, index)
        name = str(point.get("name") or "").strip()
        summary = str(point.get("summary") or "").strip()
        catalog_lines.append(f"{pid}\t{name}\t{summary}")
    catalog = "\n".join(catalog_lines)
    task_prompt = """
你是课程知识结构分析助手。把给定的知识点按学科语义归并成 4-8 个「模块/章节」，要求：
- 模块划分采用学科标准章节架构：按这门课在教科书/教学大纲中的标准章节主题划分（如操作系统 → 内存管理/进程管理/文件系统管理/输入输出设备管理），每个标准章节独立成模块，模块内保留其小节知识点。
- 不要把「基础概念」「综合应用」这类学习阶段当模块，也不要把多个标准章节拼成混合模块（如「I/O 与文件系统」应拆开）；「跨章节综合/冲刺」类内容可保留为最末一个模块。
- 模块名必须贴合课程语境（使用当前课程教材或教学大纲中的标准章节名称），不得使用「模块1/板块A」这类空泛占位名。
- 同一主题的知识点归到同一模块；模块顺序遵循教材标准讲授主线。
- 每个知识点必须归到且仅归到一个模块；moduleId 必须命中 modules 中已声明的某个 id。
只返回 JSON：
{"modules":[{"id":"mod-英文短横线 id","title":"模块名","order":1}],"assignments":[{"pointId":"知识点 id","moduleId":"对应模块 id"}]}
"""
    user_content = f"知识点清单（id\\t名称\\t说明）：\n{catalog}"
    raw = _extract_json(
        _model_completion(build_model_messages(task_prompt, user_content), json_mode=True)
    )
    modules_raw = raw.get("modules") if isinstance(raw, dict) else None
    assignments_raw = raw.get("assignments") if isinstance(raw, dict) else None
    if not isinstance(modules_raw, list) or not isinstance(assignments_raw, list):
        raise ValueError("LLM 聚类返回结构不完整")

    modules: list[dict[str, Any]] = []
    valid_ids: set[str] = set()
    for seq, module in enumerate(modules_raw, start=1):
        if not isinstance(module, dict):
            continue
        mid = str(module.get("id") or "").strip()
        if not mid or mid in valid_ids:
            continue
        valid_ids.add(mid)
        raw_order = module.get("order")
        order = int(raw_order) if isinstance(raw_order, (int, float)) and not isinstance(raw_order, bool) else seq
        title = str(module.get("title") or mid).strip() or mid
        modules.append({"id": mid, "title": title, "order": order})
    if not modules:
        raise ValueError("LLM 未返回有效模块")

    assignment: dict[str, str] = {}
    for entry in assignments_raw:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("pointId") or "").strip()
        mid = str(entry.get("moduleId") or "").strip()
        if pid and mid in valid_ids:
            assignment[pid] = mid
    if not assignment:
        raise ValueError("LLM 未给出有效归并")
    return modules, assignment


def regroup_course_modules(course_id: str) -> dict[str, Any]:
    """用 LLM 语义聚类刷新课程的模块层级，写回 workspace.modules 与 knowledgePoint.moduleId，
    再重新生成知识地图返回。模型未配置或聚类失败时回退到 resolve_course_modules 的确定性聚类，
    保证端点永远可用。"""
    workspace = load_workspace(course_id, refresh_materials=False)
    points = [point for point in workspace.get("knowledgePoints", []) if isinstance(point, dict)]

    candidate_modules: list[dict[str, Any]] | None = None
    assignment: dict[str, str] = {}
    if points:
        try:
            candidate_modules, assignment = _llm_regroup_modules(points)
        except Exception:
            candidate_modules = None

    if candidate_modules is None:
        candidate_modules, assignment = resolve_course_modules(workspace)

    workspace["modules"] = candidate_modules
    for index, point in enumerate(points):
        pid = _knowledge_point_pid(point, index)
        point["moduleId"] = assignment.get(pid, "")
    save_workspace(workspace, course_id)
    return generate_mind_map(course_id)


def generate_mind_map(course_id: str) -> dict[str, Any]:
    workspace = load_workspace(course_id, refresh_materials=False)
    previous_map: dict[str, Any] = {}
    try:
        previous_map = load_mind_map(course_id)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        previous_map = {}

    previous_nodes = {
        str(node.get("id")): node
        for node in previous_map.get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    occupied_ids: set[str] = set()

    def node_id(prefix: str, value: Any) -> str:
        raw = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or prefix)).strip("-").lower()
        digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:8]
        return f"{prefix}-{raw[:50] or digest}-{digest}"

    def add_node(node: dict[str, Any], *, column: int, row: int) -> str:
        base_id = str(node["id"])
        unique_id = base_id
        counter = 2
        while unique_id in occupied_ids:
            unique_id = f"{base_id}-{counter}"
            counter += 1
        occupied_ids.add(unique_id)
        previous = previous_nodes.get(unique_id, previous_nodes.get(base_id, {}))
        nodes.append(
            {
                **node,
                "id": unique_id,
                "position": previous.get("position") if isinstance(previous.get("position"), dict) else {"x": column * 280, "y": row * 132},
                "collapsed": bool(previous.get("collapsed", node.get("collapsed", False))),
            }
        )
        return unique_id

    def add_edge(source: str, target: str, label: str = "") -> None:
        edge_id = f"edge-{source}-{target}"
        edges.append({"id": edge_id, "source": source, "target": target, "label": label})

    course = workspace.get("course", {})
    course_node_id = add_node(
        {
            "id": f"course-{course_id}",
            "type": "course",
            "title": str(course.get("name", "当前课程")),
            "summary": str(workspace.get("assessmentProfile", {}).get("summary", "")),
            "status": str(workspace.get("diagnostic", {}).get("estimatedScore", "")),
        },
        column=0,
        row=0,
    )

    chapter_ids: dict[str, str] = {}

    def chapter_for(label: str, row_hint: int, *, kind: str = "") -> str:
        normalized_label = label.strip() or "课程知识点"
        if normalized_label not in chapter_ids:
            node_payload: dict[str, Any] = {
                "id": node_id("chapter", normalized_label),
                "type": "chapter",
                "title": normalized_label,
                "summary": "由课程资料、复习任务和知识点自动归并。",
            }
            if kind:
                node_payload["kind"] = kind
            chapter_id = add_node(node_payload, column=1, row=row_hint)
            chapter_ids[normalized_label] = chapter_id
            add_edge(course_node_id, chapter_id, "章节")
        return chapter_ids[normalized_label]

    # 课程→模块（chapter）层级：由资料结构、source、知识点名自动归并，
    # 不再用整段 source 当归并键，避免每个知识点各自成章。
    modules, point_to_module = resolve_course_modules(workspace)
    module_node_ids: dict[str, str] = {}
    for module in modules:
        module_node_id = add_node(
            {
                "id": f"module-{module['id']}",
                "type": "chapter",
                "title": str(module.get("title", "课程章节")),
                "summary": "按学科主题划分的知识模块。",
                "kind": "module",
                "order": module.get("order"),
            },
            column=1,
            row=int(module.get("order") or 0),
        )
        module_node_ids[module["id"]] = module_node_id
        add_edge(course_node_id, module_node_id, "模块")

    knowledge_points: list[dict[str, Any]] = [
        point for point in workspace.get("knowledgePoints", []) if isinstance(point, dict)
    ]
    knowledge_ids: dict[str, str] = {}
    prerequisite_sources: dict[str, list[str]] = {}
    for index, point in enumerate(knowledge_points):
        point_id = _knowledge_point_pid(point, index)
        prereq_list = point.get("prerequisites")
        if isinstance(prereq_list, list) and prereq_list:
            prerequisite_sources[point_id] = [str(item) for item in prereq_list]
        parent_id = module_node_ids.get(point_to_module.get(point_id)) or course_node_id
        knowledge_id = add_node(
            {
                "id": f"knowledge-{point_id}",
                "type": "knowledge",
                "title": str(point.get("name", "知识点")),
                "summary": str(point.get("summary", "")),
                "knowledgePointId": point_id,
                "mastery": int(point.get("mastery", 0)),
                "weight": int(point.get("weight", 0)),
                "status": "薄弱" if int(point.get("mastery", 0)) < 60 else "巩固" if int(point.get("mastery", 0)) < 85 else "已掌握",
            },
            column=2,
            row=index,
        )
        knowledge_ids[point_id] = knowledge_id
        add_edge(parent_id, knowledge_id, "知识点")

    # 知识点之间的前置依赖边（前置 → 依赖方）：跨模块也照画，
    # 前端 elk 布局会过滤掉这类边（保持树形稳定），仅在布局后叠加绘制。
    for dependent_id, prereq_ids in prerequisite_sources.items():
        for prereq in prereq_ids:
            if prereq in knowledge_ids and dependent_id in knowledge_ids:
                add_edge(
                    knowledge_ids[prereq],
                    knowledge_ids[dependent_id],
                    study_scheduler.PREREQUISITE_EDGE_LABEL,
                )

    task_chapter_id = chapter_for("复习任务", len(chapter_ids) + 1, kind="bucket")
    for index, task in enumerate(workspace.get("tasks", [])):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or node_id("task", task.get("title", index)))
        parent_id = knowledge_ids.get(str(task.get("knowledgePointId", "")), task_chapter_id)
        map_task_id = add_node(
            {
                "id": f"task-{task_id}",
                "type": "task",
                "title": str(task.get("title", "复习任务")),
                "summary": str(task.get("description", "")),
                "taskId": task_id,
                "knowledgePointId": str(task.get("knowledgePointId", "")),
                "source": str(task.get("source", "")),
                "weight": int(task.get("weight", 0)),
                "status": str(task.get("status", "")),
            },
            column=3,
            row=index,
        )
        add_edge(parent_id, map_task_id, "任务")

    question_groups = (
        ("practiceQuestions", "刷题练习"),
        ("mockQuestions", "模拟卷"),
        ("diagnosticQuestions", "摸底测试"),
    )
    question_index = 0
    for field, label in question_groups:
        for question in workspace.get(field, []):
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("id") or node_id("question", question.get("prompt", question_index)))
            parent_id = knowledge_ids.get(str(question.get("knowledgePointId", "")), task_chapter_id)
            map_question_id = add_node(
                {
                    "id": f"question-{field}-{question_id}",
                    "type": "question",
                    "title": str(question.get("prompt", "练习题"))[:80],
                    "summary": str(question.get("explanation", "")),
                    "questionId": question_id,
                    "knowledgePointId": str(question.get("knowledgePointId", "")),
                    "source": str(question.get("source", label)),
                    "weight": int(question.get("score", 0)),
                    "status": label,
                },
                column=4,
                row=question_index,
            )
            add_edge(parent_id, map_question_id, "题目")
            question_index += 1

    error_chapter_id = chapter_for("错题回顾", len(chapter_ids) + 3, kind="bucket")
    for index, wrong_answer in enumerate(workspace.get("wrongAnswers", [])):
        if not isinstance(wrong_answer, dict):
            continue
        wrong_id = str(wrong_answer.get("id") or node_id("wrong", wrong_answer.get("title", index)))
        parent_id = error_chapter_id
        question_id = str(wrong_answer.get("questionId", ""))
        for question in workspace.get("practiceQuestions", []) + workspace.get("mockQuestions", []) + workspace.get("diagnosticQuestions", []):
            if isinstance(question, dict) and str(question.get("id")) == question_id:
                parent_id = knowledge_ids.get(str(question.get("knowledgePointId", "")), error_chapter_id)
                break
        map_wrong_id = add_node(
            {
                "id": f"wrong-{wrong_id}",
                "type": "wrongAnswer",
                "title": str(wrong_answer.get("title", "错题")),
                "summary": str(wrong_answer.get("mistakeType", "")),
                "wrongAnswerId": wrong_id,
                "questionId": question_id,
                "source": str(wrong_answer.get("source", wrong_answer.get("tag", ""))),
                "status": "已复盘" if wrong_answer.get("isReviewed") else "待复盘",
            },
            column=4,
            row=question_index + index,
        )
        add_edge(parent_id, map_wrong_id, "错题")

    mind_map = {
        "version": 1,
        "courseId": course_id,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceRevision": int(workspace.get("revision", 0)),
        "layout": "tree-right",
        "viewport": previous_map.get("viewport", {"x": 72, "y": 120, "zoom": 0.88}),
        "nodes": nodes,
        "edges": edges,
    }
    return save_mind_map(mind_map, course_id)


# ------------------------------------------------------------------
# 练习/错题/模拟卷域 re-export（实现已抽到 practice.py，阶段2-5）。
# 打桩面说明：practice.py 的 load_workspace / save_workspace /
# get_course_prompt / _model_completion / _model_json / _extract_json /
# _content_generation_lock / _workspace_is_planned / _review_session_days
# 均在函数体内延迟 import 本模块，monkeypatch study_service 命名空间依旧生效。
# ------------------------------------------------------------------
from .practice import (  # noqa: E402,F401
    _ai_review_wrong_answer,
    _answer_label,
    _append_practice_questions,
    _estimate_score,
    _find_any_question,
    _find_question,
    _grade_mock_written_answer,
    _is_written_mock_question,
    _knowledge_point_name,
    _normalize_generated_practice_questions,
    _prioritize_tasks,
    _record_written_wrong_answer,
    _record_wrong_answer,
    _update_mastery,
    clear_mock_result,
    clear_practice_answer,
    repair_course_mock_questions,
    submit_mock_answers,
    submit_practice_answer,
    submit_wrong_answer_retry,
)


# ------------------------------------------------------------------
# 复习计划域 re-export（实现已抽到 review_plan.py，阶段2-6）。
# 打桩面说明：review_plan.py 的 load_workspace / save_workspace /
# get_course_prompt / _read_strategy_document / _write_strategy_document /
# _model_completion / _extract_json / build_model_messages /
# _review_session_days / record_review_progress 均在函数体内延迟
# import 本模块，monkeypatch study_service 命名空间依旧生效。
# ------------------------------------------------------------------
from .review_plan import (  # noqa: E402,F401
    _parse_plan_date,
    build_daily_progress,
    delete_time_entry,
    maintain_review_plan,
    rebalance_daily_plan,
    record_time,
    replan_review_mainline,
    update_workspace_state,
)


# ------------------------------------------------------------------
# Agent 对话域 re-export（实现已抽到 agent_chat.py，阶段2-7）。
# 打桩面说明：agent_chat.py 的 load_workspace / save_workspace /
# get_course_prompt / get_user_profile_prompt / PLATFORM_SYSTEM_PROMPT /
# build_model_messages / _model_completion / _extract_json /
# _model_agent_turn / _stream_model_turn / _review_session_days 均在函数
# 体内延迟 import 本模块，monkeypatch study_service 命名空间依旧生效。
# ------------------------------------------------------------------
from .agent_chat import (  # noqa: E402,F401
    CONVERSATION_RECENT_TURNS,
    CONVERSATION_SUMMARY_BATCH,
    _agent_chat_legacy,
    _build_agent_messages,
    _maintain_rolling_summary,
    _sse,
    _summarize_chat_memories,
    _summarize_turn_batch,
    agent_chat,
    agent_chat_stream,
)
