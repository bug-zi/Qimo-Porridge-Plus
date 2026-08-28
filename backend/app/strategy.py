"""策略文档域（阶段2-8 从 study_service.py 抽取）。

职责：复习计划/课程总 Prompt 两份策略文档的读写与版本化（_strategy_document_paths /
_validate_strategy_content / _write_strategy_document / _read_strategy_document /
get_course_prompt / get_strategy_documents）、初稿生成（generate_strategy_documents 与
legacy 路径 _generate_strategy_documents_legacy）、用户审阅保存（save_strategy_documents /
update_course_prompt）、维护标记（mark_strategy_maintenance_pending）、以及策略草稿的
对话式修订（revise_strategy_draft，纯草稿变换不落盘）。

依赖方向：strategy → workspace / agents / knowledge_service / material_parser
（跨域符号经 study_service 门面延迟 import），禁止模块级 import study_service（成环）。

与 practice.py 相同的缝合点约定：load_workspace / save_workspace /
get_user_profile_prompt / build_model_messages / _extract_json / _model_completion /
_model_json / _stream_model_turn / _sse / _source_context / scan_course_materials /
sync_course_knowledge / retrieve_material_context / _strategy_directory /
_atomic_write_text 均为跨域符号——测试惯用 monkeypatch.setattr(study_service, ...)
打桩，故本模块在函数体内延迟 import study_service，调用时读取（可能已被测试替换的）
命名空间。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths


def _strategy_document_paths(course_id: str, document_key: str, version: int) -> tuple[Path, Path]:
    from .study_service import _strategy_directory

    filename = "review-plan.md" if document_key == "reviewPlan" else "course-prompt.md"
    history_name = filename.removesuffix(".md") + f"-v{version:04d}.md"
    strategy_directory = _strategy_directory(course_id)
    return strategy_directory / filename, strategy_directory / "history" / history_name


def _validate_strategy_content(document_key: str, content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("复习计划和课程总 Prompt 不能为空")
    return normalized + "\n"


def _write_strategy_document(
    workspace: dict[str, Any],
    course_id: str,
    document_key: str,
    content: str,
    *,
    updated_by: str,
    change_summary: str = "",
) -> dict[str, Any]:
    from .study_service import _atomic_write_text

    normalized = _validate_strategy_content(document_key, content)
    strategy_documents = workspace.setdefault("strategyDocuments", {})
    current = strategy_documents.get(document_key, {})
    version = int(current.get("version", 0)) + 1
    current_path, history_path = _strategy_document_paths(course_id, document_key, version)
    _atomic_write_text(history_path, normalized)
    _atomic_write_text(current_path, normalized)
    metadata = {
        "path": str(current_path.relative_to(paths.DATA_DIRECTORY)).replace("\\", "/"),
        "version": version,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "updatedBy": updated_by,
        "changeSummary": change_summary,
    }
    strategy_documents[document_key] = metadata
    return metadata


def _read_strategy_document(course_id: str, document_key: str) -> str:
    current_path, _ = _strategy_document_paths(course_id, document_key, 1)
    return current_path.read_text(encoding="utf-8") if current_path.exists() else ""


def get_course_prompt(course_id: str) -> str:
    return _read_strategy_document(course_id, "coursePrompt")


def get_strategy_documents(course_id: str) -> dict[str, Any]:
    from .study_service import load_workspace

    workspace = load_workspace(course_id, refresh_materials=False)
    strategy_documents = workspace.get("strategyDocuments", {})

    def hydrate(document_key: str) -> dict[str, Any]:
        metadata = strategy_documents.get(document_key, {})
        return {
            "content": _read_strategy_document(course_id, document_key),
            "version": int(metadata.get("version", 0)),
            "updatedAt": str(metadata.get("updatedAt", "")),
            "updatedBy": str(metadata.get("updatedBy", "ai")),
            "changeSummary": str(metadata.get("changeSummary", "")),
        }

    return {
        "status": strategy_documents.get("status", "generating"),
        "reviewPlan": hydrate("reviewPlan"),
        "coursePrompt": hydrate("coursePrompt"),
        "maintenancePending": bool(strategy_documents.get("maintenancePending", False)),
        "maintenanceError": str(strategy_documents.get("maintenanceError", "")),
    }


def _generate_strategy_documents_legacy(course_id: str) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _extract_json,
        _model_completion,
        _source_context,
        build_model_messages,
        load_workspace,
        save_workspace,
        scan_course_materials,
    )

    workspace = load_workspace(course_id, refresh_materials=False)
    onboarding = workspace.get("onboarding", {})
    if onboarding.get("status") != "strategy-review":
        raise ValueError("请先完成摸底测试")
    materials = scan_course_materials(course_id)
    context = _source_context(materials, course_id)
    task_prompt = """
根据课程资料和用户复习目标，同时生成两份可由用户审阅的 Markdown 初稿。摸底测试仅供用户体验题目，不得影响知识点重要程度、讲解篇幅或课程顺序。只返回 JSON 对象：
{
  "reviewPlanMarkdown":"精简复习计划 Markdown",
  "coursePromptMarkdown":"完整课程总 Prompt Markdown"
}

复习计划必须短、清楚、能直接执行，用户可见正文只保留以下三个二级章节，顺序不得改变，不得增加其他二级章节：
# 课程速通复习总计划
## 主线规划
## 知识点与讲解深度
## 每日计划

【课程顺序硬合同】
1. 先识别主资料的目录树及章节、小节、页码或课件原始顺序，再严格按该顺序安排知识点和每天的新课。主资料是用户标记的主资料、核心讲义或教材；辅资料只能在对应知识点原位置补充例题、题型、易错点和解释，不能改变主线。
2. 若没有主资料标记，严格按照上传资料自然顺序以及各资料内部目录、章节、小节、页码或课件出现顺序推进。
3. 知识点没有“学习优先级”，只有“重要程度”。重要程度、考试价值、难度、正式学习中的薄弱程度和失分情况，只能决定知识点在原位置的讲解篇幅、分钟数、例题和自测数量、复练强度；严禁据此提前、延后、插队、跨章或交换知识点顺序。
4. 复练只能作为明确标注的复习块插在当天末尾或后续天，不能打断新知识的原始推进顺序。任何动态调整也只能增减时长、题量和复练，不能重排主线。

【三个章节的内容合同】
1. `主线规划`：只用 3-6 个短段或有序项，按资料框架说明从哪个章节讲到哪个章节、相邻章节如何衔接。不得写“学习目标与时间约束”“总体时间分配”“动态调整规则”“当前进度快照”等套话。
2. `知识点与讲解深度`：按主资料原始顺序使用一张表格，列为 `顺序 | 知识点 | 重要程度 | 讲解与训练安排`。重要程度只能写“重点详讲 / 常规讲解 / 简要覆盖”，不得出现“高/中/低优先级”“排序理由”或暗示先学重要知识点的措辞。
3. `每日计划`：从第1天到第N天逐日列出，不得缺天、合并或使用“后续同理”。每天只保留：一句当日目标、一张执行表。
4. 每日执行表列为 `用时 | 按主线学习的知识点 | 怎么学与完成什么 | 验收标准`，每个学习块必须明确分钟数、具体知识点、动作、可检查产出和量化标准。每天总分钟数使用可用时间的80%-100%，不得超出预算。
5. 如果 reviewCount 小于复习天数 N，仅在按间隔分布的复习日安排完整学习内容，其余天标为“休息日（回顾/机动）”，但仍保留 N 天。最后一个学习日完成综合检测和错题回收。
6. 只使用输入中真实存在的课程事实；证据不足的范围写“待用户确认”。用户可见正文不得展示资料出处、来源标签或内部字段。
7. 详细定义、教材式讲解和完整例题留给后续课程内容生成；总计划不展开讲课，不重复同一要求。

输出前自行检查：知识点表和每日首次学习的知识点顺序是否与主资料完全一致；重要程度是否只影响详略而未影响顺序；是否只有三个二级章节；是否恰好生成 N 天；任一项不满足时先内部修正，不输出检查过程。

课程总 Prompt 必须依次包含：角色与最终目标、资料使用规则、教学与解释方式、出题与讲评规则、复习计划调整规则、输出格式与语言、用户特别要求。其中必须写明：课程严格按主资料框架和章节顺序生成；知识点重要程度只影响内容深度、篇幅、题量和复练，不影响课程顺序。
两份文档必须具体使用当前课程事实，不得声称尚未发生的学习进度。
    """
    payload = {
        "course": workspace.get("course", {}),
        "onboarding": onboarding,
        "assessmentProfile": workspace.get("assessmentProfile", {}),
    }
    strategy_documents = workspace.setdefault("strategyDocuments", {})
    strategy_documents["status"] = "generating"
    strategy_documents["maintenanceError"] = ""
    save_workspace(workspace, course_id)
    try:
        parsed = _extract_json(
            _model_completion(
                build_model_messages(
                    task_prompt,
                    f"【课程状态】\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n{context}",
                ),
                json_mode=True,
            )
        )
        review_plan = str(parsed.get("reviewPlanMarkdown", ""))
        course_prompt = str(parsed.get("coursePromptMarkdown", ""))
        _write_strategy_document(
            workspace,
            course_id,
            "reviewPlan",
            review_plan,
            updated_by="ai",
            change_summary="根据课程资料和用户目标生成初稿",
        )
        _write_strategy_document(
            workspace,
            course_id,
            "coursePrompt",
            course_prompt,
            updated_by="ai",
            change_summary="根据课程资料和用户目标生成初稿",
        )
        strategy_documents["status"] = "review"
        strategy_documents["maintenancePending"] = False
        save_workspace(workspace, course_id)
        return get_strategy_documents(course_id)
    except Exception as error:
        strategy_documents["status"] = "maintenance-error"
        strategy_documents["maintenanceError"] = str(error)
        save_workspace(workspace, course_id)
        raise RuntimeError(f"策略文档生成失败：{error}") from error


def generate_strategy_documents(course_id: str) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _model_json,
        _source_context,
        load_workspace,
        retrieve_material_context,
        run_strategy_workflow,
        save_workspace,
        scan_course_materials,
        sync_course_knowledge,
    )

    workspace = load_workspace(course_id, refresh_materials=False)
    onboarding = workspace.get("onboarding", {})
    if onboarding.get("status") != "strategy-review":
        raise ValueError("请先完成摸底测试")
    strategy_documents = workspace.setdefault("strategyDocuments", {})
    strategy_documents["status"] = "generating"
    strategy_documents["maintenanceError"] = ""
    save_workspace(workspace, course_id)
    try:
        sync_course_knowledge(course_id, workspace)
        retrieval = retrieve_material_context(
            course_id,
            "考试范围 核心知识点 高频题型 公式 重点 难点 老师强调 真题",
            limit=18,
        )
        evidence_context = retrieval.get("context", "") or _source_context(scan_course_materials(course_id), course_id)
        result = run_strategy_workflow(course_id, workspace, evidence_context, _model_json)
        latest_workspace = load_workspace(course_id, refresh_materials=False)
        _write_strategy_document(
            latest_workspace,
            course_id,
            "reviewPlan",
            str(result["reviewPlanMarkdown"]),
            updated_by="strategy_planner",
            change_summary="由知识整理 Agent 与策略规划 Agent 生成初稿",
        )
        _write_strategy_document(
            latest_workspace,
            course_id,
            "coursePrompt",
            str(result["coursePromptMarkdown"]),
            updated_by="platform",
            change_summary="根据课程画像生成可由用户维护的初始课程规则",
        )
        latest_documents = latest_workspace.setdefault("strategyDocuments", {})
        latest_documents["status"] = "review"
        latest_documents["maintenancePending"] = False
        latest_documents["lastAgentRunId"] = result["runId"]
        save_workspace(latest_workspace, course_id)
        return get_strategy_documents(course_id)
    except Exception as error:
        latest_workspace = load_workspace(course_id, refresh_materials=False)
        latest_documents = latest_workspace.setdefault("strategyDocuments", {})
        latest_documents["status"] = "maintenance-error"
        latest_documents["maintenanceError"] = str(error)
        save_workspace(latest_workspace, course_id)
        raise RuntimeError(f"多 Agent 策略生成失败：{error}") from error


def save_strategy_documents(
    course_id: str,
    review_plan: str,
    course_prompt: str,
    *,
    expected_review_plan_version: int,
    expected_course_prompt_version: int,
) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import load_workspace, save_workspace

    workspace = load_workspace(course_id, refresh_materials=False)
    strategy_documents = workspace.get("strategyDocuments", {})
    if int(strategy_documents.get("reviewPlan", {}).get("version", 0)) != expected_review_plan_version:
        raise RuntimeError("复习计划已被更新，请刷新后重试")
    if int(strategy_documents.get("coursePrompt", {}).get("version", 0)) != expected_course_prompt_version:
        raise RuntimeError("课程总 Prompt 已被更新，请刷新后重试")
    _validate_strategy_content("reviewPlan", review_plan)
    _validate_strategy_content("coursePrompt", course_prompt)
    _write_strategy_document(
        workspace,
        course_id,
        "reviewPlan",
        review_plan,
        updated_by="user",
        change_summary="用户审阅并保存",
    )
    _write_strategy_document(
        workspace,
        course_id,
        "coursePrompt",
        course_prompt,
        updated_by="user",
        change_summary="用户审阅并保存",
    )
    workspace["strategyDocuments"]["status"] = "review"
    save_workspace(workspace, course_id)
    return get_strategy_documents(course_id)


#策略草稿对话修订：AI 只变换前端传来的草稿文本，不落盘、不写对话记忆。
REPLY_DELIMITER = "<<<REPLY>>>"
REVIEW_PLAN_DELIMITER = "<<<REVIEW_PLAN>>>"
COURSE_PROMPT_DELIMITER = "<<<COURSE_PROMPT>>>"

STRATEGY_REVISION_TASK_PROMPT = f"""
你是复习策略草稿修订助手。用户正在审阅 AI 初步生成的《复习计划》和《课程总 Prompt》两份 Markdown 草稿，
会用自己的话提出修改诉求；你需要据此返回修订后的完整草稿。

输出必须是且仅是以下格式（三段定界标记独占一行，不得加代码围栏）：
{REPLY_DELIMITER}
（给用户看的回复：改了什么、为什么这样改，1-4 句中文）
{REVIEW_PLAN_DELIMITER}
（修订后的完整复习计划 Markdown 全文；即使没有改动也要原样返回全文，不得省略或用“略”代替）
{COURSE_PROMPT_DELIMITER}
（修订后的完整课程总 Prompt Markdown 全文；即使没有改动也要原样返回全文）

修订约束：
1. 保持逐日结构（### 第N天）和一级/二级章节标题不变，除非诉求明确要求增删天数或章节；
2. 只能使用课程资料、用户设置与当前草稿中已有的事实，不得编造知识点、题型或出处；
3. 每日学习块总分钟数仍应落在用户每日可用时间的 90%-100%，除非诉求明确要求改变总量；
4. 诉求只涉及其中一份草稿时，另一份原样返回全文；
5. 诉求含义不清时，在 REPLY 段提出澄清问题，两份草稿仍各返回当前全文，不得自行臆测改写。
"""


def _split_revision_output(raw: str) -> tuple[str, str, str]:
    """把模型输出切成 reply / reviewPlan / coursePrompt 三段；缺段或空段抛 ValueError。"""
    reply_marker = raw.find(REPLY_DELIMITER)
    plan_marker = raw.find(REVIEW_PLAN_DELIMITER)
    prompt_marker = raw.find(COURSE_PROMPT_DELIMITER)
    if reply_marker < 0 or plan_marker < 0 or prompt_marker < 0 or not (reply_marker < plan_marker < prompt_marker):
        raise ValueError("模型输出缺少修订定界标记")
    reply = raw[reply_marker + len(REPLY_DELIMITER):plan_marker].strip()
    review_plan = raw[plan_marker + len(REVIEW_PLAN_DELIMITER):prompt_marker].strip()
    course_prompt = raw[prompt_marker + len(COURSE_PROMPT_DELIMITER):].strip()
    if not reply or not review_plan or not course_prompt:
        raise ValueError("模型输出的修订内容不完整")
    return reply, review_plan, course_prompt


def revise_strategy_draft(
    course_id: str,
    message: str,
    history: list[dict[str, Any]],
    review_plan: str,
    course_prompt: str,
    *,
    owner_id: str = "",
):
    """流式修订策略草稿，yield SSE 文本块。纯草稿变换：不写 workspace、不写对话记忆。

    事件：token（reply 段的打字机增量）/ done（{reply, reviewPlan, coursePrompt}）/ error。
    模型输出不合规时只发 error，绝不返回半份草稿。
    """
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    # test_strategy_revision 打桩 study_service._stream_model_turn，必须经本门面读取。
    from .study_service import (
        _sse,
        _stream_model_turn,
        build_model_messages,
        get_user_profile_prompt,
        load_workspace,
    )

    load_workspace(course_id, refresh_materials=False)  # 课程不存在 → FileNotFoundError（路由层转 404）
    _validate_strategy_content("reviewPlan", review_plan)
    _validate_strategy_content("coursePrompt", course_prompt)

    user_content = (
        f"【当前复习计划草稿】\n{review_plan.strip()}\n\n"
        f"【当前课程总 Prompt 草稿】\n{course_prompt.strip()}\n\n"
        f"【修改诉求】\n{message.strip()}"
    )
    messages = build_model_messages(
        STRATEGY_REVISION_TASK_PROMPT,
        user_content,
        user_profile_prompt=get_user_profile_prompt(owner_id)["content"],
    )
    # build_model_messages 已把 user_content 作为末条 user 消息；会话内 history 插到它前面
    final_message = messages.pop()
    for turn in history:
        role = str(turn.get("role", ""))
        content = str(turn.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append(final_message)

    raw_parts: list[str] = []
    sent_reply_chars = 0  # 已转发进打字机的 reply 段字符数
    try:
        for kind, payload in _stream_model_turn(messages, []):
            if kind != "token" or not isinstance(payload, str) or not payload:
                continue
            raw_parts.append(payload)
            current = "".join(raw_parts)
            # 打字机只转发 reply 段（去掉开头的 <<<REPLY>>> 标记行）；草稿全文不进打字机
            reply_end = current.find(REVIEW_PLAN_DELIMITER)
            visible = current if reply_end < 0 else current[:reply_end]
            stripped = visible.lstrip()
            if stripped.startswith(REPLY_DELIMITER):
                visible_reply = stripped[len(REPLY_DELIMITER):]
            else:
                # 标记可能只流到一半：尾部预留一个标记长度的缓冲，避免把半个标记打进打字机
                visible_reply = visible[: max(0, len(visible) - len(REPLY_DELIMITER))]
            if len(visible_reply) > sent_reply_chars:
                yield _sse("token", {"text": visible_reply[sent_reply_chars:]})
                sent_reply_chars = len(visible_reply)
    except Exception as error:
        yield _sse("error", {"message": f"策略修订暂时失败：{error}"})
        return

    try:
        reply, new_plan, new_prompt = _split_revision_output("".join(raw_parts))
        _validate_strategy_content("reviewPlan", new_plan)
        _validate_strategy_content("coursePrompt", new_prompt)
    except ValueError as error:
        yield _sse("error", {"message": f"本次修订结果不完整，请换个说法再试：{error}"})
        return

    yield _sse(
        "done",
        {"reply": reply, "reviewPlan": new_plan, "coursePrompt": new_prompt},
    )

def update_course_prompt(
    course_id: str,
    course_prompt: str,
    *,
    expected_version: int,
) -> dict[str, Any]:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import load_workspace, save_workspace

    workspace = load_workspace(course_id, refresh_materials=False)
    current_version = int(workspace.get("strategyDocuments", {}).get("coursePrompt", {}).get("version", 0))
    if current_version != expected_version:
        raise RuntimeError("课程总 Prompt 已被更新，请刷新后重试")
    _write_strategy_document(
        workspace,
        course_id,
        "coursePrompt",
        course_prompt,
        updated_by="user",
        change_summary="用户更新课程级复习指令",
    )
    save_workspace(workspace, course_id)
    return get_strategy_documents(course_id)


def mark_strategy_maintenance_pending(course_id: str, event: str) -> bool:
    # 缝合点：延迟 import study_service（保住测试的 monkeypatch 打桩面）。
    from .study_service import (
        _read_strategy_document,
        load_workspace,
        save_workspace,
    )

    workspace = load_workspace(course_id, refresh_materials=False)
    strategy_documents = workspace.get("strategyDocuments", {})
    if strategy_documents.get("status") != "approved" or not _read_strategy_document(course_id, "reviewPlan"):
        return False
    strategy_documents["maintenancePending"] = True
    strategy_documents["maintenanceEvent"] = event
    strategy_documents["maintenanceError"] = ""
    save_workspace(workspace, course_id)
    return True
