from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from functools import wraps
from typing import Any, Callable

from .course_feedback_store import (
    course_feedback_lock as _course_feedback_lock,
    mutate_feedback_entries as _mutate_feedback_entries,
    read_feedback_entries as _store_read_feedback_entries,
    read_rules_store as _store_read_rules_store,
    write_feedback_entries as _store_write_feedback_entries,
    write_rules_store as _store_write_rules_store,
)

JsonModelCall = Callable[[str, str, str], dict[str, Any]]

FEEDBACK_VERSION = 1
MAX_SELECTED_TEXT_LENGTH = 4000
MAX_USER_COMMENT_LENGTH = 2000
MAX_CONTEXT_TEXT_LENGTH = 8000
MAX_RULES = 24
MAX_RULE_PROMPT_CHARS = 5000
MAX_STRONG_DIRECTIVES = 40
MAX_SESSION_ATTEMPTS = 8
TERMINAL_FEEDBACK_STATUSES = {"accepted", "abandoned", "expired"}


def _locked_course_feedback(operation: Callable[..., Any]) -> Callable[..., Any]:
    """Hold one course RLock across a complete service transaction."""
    @wraps(operation)
    def wrapped(course_id: str, *args: Any, **kwargs: Any) -> Any:
        with _course_feedback_lock(course_id):
            return operation(course_id, *args, **kwargs)
    return wrapped


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _safe_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    text_keys = {"beforeText", "afterText", "sectionText", "route", "taskId", "taskTitle", "moduleId", "knowledgePointId", "sourceArea", "field", "examPointId", "exampleId", "conceptTitle", "itemIndex"}
    context: dict[str, Any] = {}
    for key, value in source.items():
        if key == "selectionFragments" and isinstance(value, list):
            fragments = []
            for item in value[:30]:
                if not isinstance(item, dict):
                    continue
                fragment = {
                    name: _clip_text(item.get(name), MAX_SELECTED_TEXT_LENGTH if name == "selectedText" else 500)
                    for name in ("selectedText", "field", "examPointId", "exampleId", "conceptTitle", "itemIndex")
                    if item.get(name) is not None
                }
                if fragment.get("selectedText") and fragment.get("field"):
                    fragments.append(fragment)
            if fragments:
                context[key] = fragments
        elif key in text_keys:
            context[key] = _clip_text(value, MAX_CONTEXT_TEXT_LENGTH if key.endswith("Text") else 500)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            context[key] = value
    return context


def _read_feedback_entries(course_id: str) -> list[dict[str, Any]]:
    return _store_read_feedback_entries(course_id)


def _write_feedback_entries(course_id: str, entries: list[dict[str, Any]]) -> None:
    _store_write_feedback_entries(course_id, entries)


def _read_rules_store(course_id: str) -> dict[str, Any]:
    return _store_read_rules_store(course_id)


def _write_rules_store(course_id: str, store: dict[str, Any]) -> None:
    normalized = {
        "version": FEEDBACK_VERSION,
        "rules": store.get("rules", []),
        "strongDirectives": store.get("strongDirectives", [])[:MAX_STRONG_DIRECTIVES],
        "summaryPrompt": _clip_text(store.get("summaryPrompt", ""), MAX_RULE_PROMPT_CHARS),
        "updatedAt": _now_iso(),
    }
    _store_write_rules_store(course_id, normalized)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return normalized[:40] or "style-rule"


def _normalize_rule(candidate: dict[str, Any], feedback_id: str) -> dict[str, Any]:
    title = _clip_text(candidate.get("title") or "课程表达优化规则", 80)
    return {
        "id": f"crule_{_slug(title)}_{uuid.uuid4().hex[:8]}",
        "status": "proposed",
        "type": _clip_text(candidate.get("type") or "teaching_style", 40),
        "title": title,
        "description": _clip_text(candidate.get("description") or candidate.get("preferredPattern") or title, 500),
        "badPattern": _clip_text(candidate.get("badPattern") or "", 300),
        "preferredPattern": _clip_text(candidate.get("preferredPattern") or candidate.get("description") or title, 500),
        "examples": candidate.get("examples") if isinstance(candidate.get("examples"), list) else [],
        "sourceFeedbackIds": [feedback_id],
        "weight": 1.0,
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    }


def _merge_rule(rules: list[dict[str, Any]], candidate: dict[str, Any], feedback_id: str) -> list[dict[str, Any]]:
    next_rule = _normalize_rule(candidate, feedback_id)
    next_title = next_rule["title"].strip().lower()
    next_type = next_rule["type"].strip().lower()
    for rule in rules:
        if str(rule.get("title", "")).strip().lower() == next_title or (
            str(rule.get("type", "")).strip().lower() == next_type
            and str(rule.get("preferredPattern", "")).strip() == next_rule["preferredPattern"]
        ):
            if rule.get("status") == "active":
                rule["proposedSourceFeedbackIds"] = list(dict.fromkeys([*(rule.get("proposedSourceFeedbackIds") or []), feedback_id]))
            else:
                rule["sourceFeedbackIds"] = list(dict.fromkeys([*(rule.get("sourceFeedbackIds") or []), feedback_id]))
            rule["description"] = next_rule["description"] or rule.get("description", "")
            rule["preferredPattern"] = next_rule["preferredPattern"] or rule.get("preferredPattern", "")
            rule["badPattern"] = next_rule["badPattern"] or rule.get("badPattern", "")
            rule["weight"] = min(3.0, float(rule.get("weight") or 1.0) + 0.15)
            rule["updatedAt"] = _now_iso()
            return rules
    return [next_rule, *rules][:MAX_RULES]


def _build_summary_prompt(rules: list[dict[str, Any]]) -> str:
    active = [rule for rule in rules if rule.get("status") == "active"][:12]
    if not active:
        return ""
    lines = [
        "以下规则来自用户对课程片段的反馈，只用于调整讲解语言、教学顺序、例子密度和速成课表达方式；不得覆盖事实依据、考试范围、资料优先级和当前任务契约。",
    ]
    for index, rule in enumerate(active, start=1):
        title = _clip_text(rule.get("title"), 80)
        preferred = _clip_text(rule.get("preferredPattern") or rule.get("description"), 260)
        bad = _clip_text(rule.get("badPattern"), 160)
        suffix = f" 避免：{bad}" if bad else ""
        lines.append(f"{index}. {title}：{preferred}{suffix}")
    return _clip_text("\n".join(lines), MAX_RULE_PROMPT_CHARS)




def _strong_directive_from_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    context = feedback.get("context") if isinstance(feedback.get("context"), dict) else {}
    return {
        "id": f"directive_{feedback.get('id', uuid.uuid4().hex[:8])}",
        "status": "proposed",
        "strength": "must",
        "scope": str(context.get("feedbackScope") or "selection"),
        "sectionId": str(context.get("sectionId") or ""),
        "sectionLabel": str(context.get("sectionLabel") or ""),
        "instruction": _clip_text(feedback.get("userComment"), MAX_USER_COMMENT_LENGTH),
        "sourceFeedbackId": str(feedback.get("id") or ""),
        "createdAt": str(feedback.get("createdAt") or _now_iso()),
    }


def _merge_strong_directive(items: list[dict[str, Any]], feedback: dict[str, Any]) -> list[dict[str, Any]]:
    directive = _strong_directive_from_feedback(feedback)
    if not directive["instruction"]:
        return items
    source_id = directive["sourceFeedbackId"]
    filtered = [item for item in items if str(item.get("sourceFeedbackId")) != source_id]
    return [directive, *filtered][:MAX_STRONG_DIRECTIVES]


def get_course_strong_directives(course_id: str) -> list[dict[str, Any]]:
    """Return explicit user instructions, including records created before directive storage existed."""
    store_items = _read_rules_store(course_id).get("strongDirectives", [])
    merged = [item for item in store_items if isinstance(item, dict) and item.get("status", "active") == "active"]
    known = {str(item.get("sourceFeedbackId")) for item in merged}
    for feedback in reversed(_read_feedback_entries(course_id)):
        context = feedback.get("context") if isinstance(feedback.get("context"), dict) else {}
        feedback_id = str(feedback.get("id") or "")
        status = str(feedback.get("status") or "")
        session = feedback.get("rewriteSession") if isinstance(feedback.get("rewriteSession"), dict) else {}
        legacy_accepted = status == "accepted" or session.get("status") == "accepted" or bool(session.get("acceptedRewrite") or session.get("acceptedGlobalRewrite"))
        if feedback_id not in known and legacy_accepted and context.get("feedbackScope") in {"section", "global"} and str(feedback.get("userComment") or "").strip():
            directive = _strong_directive_from_feedback(feedback)
            directive["status"] = "active"
            merged.append(directive); known.add(feedback_id)
    return merged[:MAX_STRONG_DIRECTIVES]


def _activate_feedback_preference(course_id: str, feedback: dict[str, Any], remember_preference: bool) -> None:
    feedback_id = str(feedback.get("id") or "")
    store = _read_rules_store(course_id)
    for rule in store.get("rules", []):
        proposed_ids = list(rule.get("proposedSourceFeedbackIds") or [])
        source_ids = list(rule.get("sourceFeedbackIds") or [])
        if feedback_id not in source_ids and feedback_id not in proposed_ids:
            continue
        rule["proposedSourceFeedbackIds"] = [item for item in proposed_ids if item != feedback_id]
        if remember_preference:
            rule["sourceFeedbackIds"] = list(dict.fromkeys([*source_ids, feedback_id]))
            rule["status"] = "active"
        elif rule.get("status") != "active":
            rule["sourceFeedbackIds"] = [item for item in source_ids if item != feedback_id]
            rule["status"] = "inactive" if not rule["sourceFeedbackIds"] else rule.get("status")
        rule["updatedAt"] = _now_iso()
    for directive in store.get("strongDirectives", []):
        if str(directive.get("sourceFeedbackId") or "") == feedback_id:
            directive["status"] = "active" if remember_preference else "inactive"
    store["summaryPrompt"] = _build_summary_prompt(store.get("rules", []))
    _write_rules_store(course_id, store)


def _compact_feedback_session(feedback: dict[str, Any]) -> None:
    session = feedback.get("rewriteSession") if isinstance(feedback.get("rewriteSession"), dict) else None
    if not session:
        return
    attempts = session.get("attempts") if isinstance(session.get("attempts"), list) else []
    session["attemptCount"] = len(attempts)
    session["attempts"] = [
        {key: item.get(key) for key in ("version", "inputComment", "accepted", "createdAt")}
        for item in attempts[-2:] if isinstance(item, dict)
    ]
    session.pop("latestProposal", None)


def get_open_course_feedback(course_id: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for feedback in reversed(_read_feedback_entries(course_id)):
        context = feedback.get("context") if isinstance(feedback.get("context"), dict) else {}
        session = feedback.get("rewriteSession") if isinstance(feedback.get("rewriteSession"), dict) else {}
        proposal = session.get("latestProposal") if isinstance(session.get("latestProposal"), dict) else None
        # The selection toolbar can only restore fragment proposals. Section-wide proposals have a
        # different shape and remain owned by AiCompanion.
        if context.get("feedbackScope") in {"section", "global"} or not proposal or "originalText" not in proposal:
            continue
        if session.get("status") == "open" or feedback.get("status") == "awaiting_confirmation":
            items.append({
                "feedbackId": str(feedback.get("id") or ""),
                "status": str(feedback.get("status") or "awaiting_confirmation"),
                "selectedText": str(feedback.get("selectedText") or ""),
                "userComment": str(feedback.get("userComment") or ""),
                "context": context,
                "rewriteProposal": proposal,
                "rewriteError": str(feedback.get("rewriteError") or ""),
            })
    return {"items": items}


def get_course_feedback_rules(course_id: str) -> dict[str, Any]:
    return _read_rules_store(course_id)


@_locked_course_feedback
def update_course_feedback_rule(course_id: str, rule_id: str, *, status: str) -> dict[str, Any]:
    if status not in {"active", "inactive", "proposed"}:
        raise ValueError("规则状态无效")
    store = _read_rules_store(course_id)
    rule = next((item for item in store.get("rules", []) if str(item.get("id") or "") == rule_id), None)
    if not rule:
        raise ValueError("反馈规则不存在")
    rule.update({"status": status, "updatedAt": _now_iso()})
    for directive in store.get("strongDirectives", []):
        source = str(directive.get("sourceFeedbackId") or "")
        if source in (rule.get("sourceFeedbackIds") or []):
            directive["status"] = "active" if status == "active" else "inactive"
    store["summaryPrompt"] = _build_summary_prompt(store.get("rules", []))
    _write_rules_store(course_id, store)
    return {"rule": rule, "rules": store}


@_locked_course_feedback
def delete_course_feedback_rule(course_id: str, rule_id: str) -> dict[str, Any]:
    store = _read_rules_store(course_id)
    matches = [item for item in store.get("rules", []) if str(item.get("id") or "") == rule_id]
    if not matches:
        raise ValueError("反馈规则不存在")
    source_ids = set(matches[0].get("sourceFeedbackIds") or [])
    store["rules"] = [item for item in store.get("rules", []) if str(item.get("id") or "") != rule_id]
    store["strongDirectives"] = [item for item in store.get("strongDirectives", []) if str(item.get("sourceFeedbackId") or "") not in source_ids]
    store["summaryPrompt"] = _build_summary_prompt(store["rules"])
    _write_rules_store(course_id, store)
    return {"deletedRuleId": rule_id, "rules": store}

@_locked_course_feedback
def merge_course_feedback_rules(course_id: str, target_rule_id: str, source_rule_ids: list[str]) -> dict[str, Any]:
    unique_source_ids = [item for item in dict.fromkeys(source_rule_ids) if item and item != target_rule_id]
    if not unique_source_ids:
        raise ValueError("请选择至少一条要合并的其他规则")
    store = _read_rules_store(course_id)
    rules = store.get("rules", []) if isinstance(store.get("rules"), list) else []
    target = next((item for item in rules if str(item.get("id") or "") == target_rule_id), None)
    if not target:
        raise ValueError("目标反馈规则不存在")
    sources = [item for item in rules if str(item.get("id") or "") in unique_source_ids]
    if len(sources) != len(unique_source_ids):
        raise ValueError("存在无法合并的反馈规则")
    all_sources = [target, *sources]
    feedback_ids: list[str] = []
    proposed_ids: list[str] = []
    for rule in all_sources:
        feedback_ids.extend(str(item) for item in (rule.get("sourceFeedbackIds") or []) if item)
        proposed_ids.extend(str(item) for item in (rule.get("proposedSourceFeedbackIds") or []) if item)
    target["sourceFeedbackIds"] = list(dict.fromkeys(feedback_ids))
    target["proposedSourceFeedbackIds"] = list(dict.fromkeys(proposed_ids))
    target["weight"] = min(3.0, sum(float(item.get("weight") or 1.0) for item in all_sources))
    target["status"] = "active" if any(item.get("status") == "active" for item in all_sources) else str(target.get("status") or "proposed")
    target["updatedAt"] = _now_iso()
    source_rule_id_set = set(unique_source_ids)
    store["rules"] = [item for item in rules if str(item.get("id") or "") not in source_rule_id_set]
    store["summaryPrompt"] = _build_summary_prompt(store["rules"])
    _write_rules_store(course_id, store)
    return {"targetRuleId": target_rule_id, "mergedRuleIds": unique_source_ids, "rule": target, "rules": store}


def get_course_feedback_rules_prompt(course_id: str) -> str:
    prompt = str(_read_rules_store(course_id).get("summaryPrompt", "")).strip()
    directives = get_course_strong_directives(course_id)
    blocks: list[str] = []
    if directives:
        lines = [
            "【用户强反馈：最高优先级生成合同】",
            "以下每条都是用户明确要求，不是可选建议。后续所有新课程必须执行；与风格模板、默认数量或示例冲突时，以这里为准。",
        ]
        for index, item in enumerate(directives, start=1):
            section = str(item.get("sectionLabel") or item.get("sectionId") or "课程内容")
            lines.append(f"MUST-{index} [{section}] {str(item.get('instruction') or '').strip()}")
        blocks.append("\n".join(lines))
    if prompt:
        blocks.append("【课程优化库：反馈分析提炼】\n" + prompt)
    return "\n\n".join(blocks)


def append_course_feedback_rules(course_id: str, course_prompt: str) -> str:
    rules_prompt = get_course_feedback_rules_prompt(course_id)
    if not rules_prompt:
        return course_prompt
    return f"{course_prompt.rstrip()}\n\n---\n\n{rules_prompt}\n"


def analyze_feedback_entry(course_id: str, feedback: dict[str, Any], model_json: JsonModelCall) -> dict[str, Any]:
    task_prompt = """
你是 Course Language Feedback Analyst Agent。你要根据用户课程意见、反馈范围和上下文，分析当前 AI 课程输出哪里不符合用户偏好，并沉淀为可复用的课程优化规则。反馈可能针对划选片段，也可能针对课程中的一个完整小节；当 context.feedbackScope=section 时，应重点提炼该小节的结构、内容组织、追加总结或教学顺序等整体偏好，不要误判成某个局部片段的措辞问题。
只返回 JSON：
{
  "problemTypes":["too_abstract|definition_first|missing_example|bad_order|too_verbose|too_formal|not_crash_course|term_without_scaffold|other"],
  "diagnosis":"结合上下文说明问题，不要只复述用户意见",
  "suggestedRewrite":"根据用户意见给出该片段的示范改写，保持事实不扩写",
  "ruleCandidate":{"type":"teaching_style|teaching_order|example_density|tone|exam_orientation|other","title":"短标题","description":"规则说明","badPattern":"应避免的表达模式","preferredPattern":"以后生成课程时应采用的表达模式"}
}
规则必须是可复用的课程生成偏好，不得要求编造资料、改变考试范围或覆盖事实依据；如果反馈只适合当前片段，也要抽象成温和的候选规则。
"""
    payload = {
        "selectedText": feedback.get("selectedText", ""),
        "userComment": feedback.get("userComment", ""),
        "context": feedback.get("context", {}),
    }
    result = model_json(task_prompt, json.dumps(payload, ensure_ascii=False, indent=2), "")
    if not isinstance(result, dict):
        raise ValueError("反馈分析没有返回 JSON 对象")
    rule_candidate = result.get("ruleCandidate")
    if not isinstance(rule_candidate, dict):
        raise ValueError("反馈分析缺少 ruleCandidate")
    return result


@_locked_course_feedback
def submit_course_feedback(
    course_id: str,
    *,
    selected_text: str,
    user_comment: str,
    context: dict[str, Any] | None,
    model_json: JsonModelCall | None = None,
) -> dict[str, Any]:
    selected = _clip_text(selected_text, MAX_SELECTED_TEXT_LENGTH)
    comment = _clip_text(user_comment, MAX_USER_COMMENT_LENGTH)
    if not selected:
        raise ValueError("请选择需要反馈的课程内容")
    if not comment:
        raise ValueError("请填写课程意见")

    feedback_id = f"cfb_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    feedback = {
        "id": feedback_id,
        "courseId": course_id,
        "selectedText": selected,
        "userComment": comment,
        "context": _safe_context(context),
        "createdAt": _now_iso(),
        "status": "pending_analysis",
        "analysis": None,
        "analysisError": "",
    }
    entries = _read_feedback_entries(course_id)
    entries.append(feedback)
    _write_feedback_entries(course_id, entries)

    message = "课程意见已记录，将用于优化后续课程生成。"
    if model_json is not None:
        try:
            analysis = analyze_feedback_entry(course_id, feedback, model_json)
            feedback["status"] = "analyzed"
            feedback["analysis"] = analysis
            store = _read_rules_store(course_id)
            store["rules"] = _merge_rule(store.get("rules", []), analysis.get("ruleCandidate", {}), feedback_id)
            if feedback.get("context", {}).get("feedbackScope") in {"section", "global"}:
                store["strongDirectives"] = _merge_strong_directive(store.get("strongDirectives", []), feedback)
            store["summaryPrompt"] = _build_summary_prompt(store["rules"])
            _write_rules_store(course_id, store)
            entries[-1] = feedback
            _write_feedback_entries(course_id, entries)
            message = "课程意见已记录，并已更新课程语言优化库。"
        except Exception as error:  # 反馈不能因模型分析失败而丢失
            feedback["analysisError"] = str(error)
            entries[-1] = feedback
            _write_feedback_entries(course_id, entries)
            message = "课程意见已记录；模型暂不可用或分析失败，稍后仍可继续用于优化。"

    return {"feedbackId": feedback_id, "status": feedback["status"], "message": message}


def list_course_feedback(course_id: str, limit: int = 50) -> dict[str, Any]:
    entries = list(reversed(_read_feedback_entries(course_id)))[: max(1, min(limit, 200))]
    return {"items": entries, "rules": _read_rules_store(course_id)}



def generate_rewrite_proposal(
    course_id: str,
    feedback_id: str,
    *,
    selected_text: str,
    user_comment: str,
    context: dict[str, Any] | None,
    model_json: JsonModelCall,
    previous_rewrite: str = "",
    refinement_comment: str = "",
) -> dict[str, Any]:
    selected = _clip_text(selected_text, MAX_SELECTED_TEXT_LENGTH)
    comment = _clip_text(user_comment, MAX_USER_COMMENT_LENGTH)
    safe_context = _safe_context(context)
    rules_prompt = get_course_feedback_rules_prompt(course_id)
    task_prompt = """
你是 Course Segment Rewriter Agent。你要根据用户划选的课程片段、上下文和用户反馈，生成当前片段的优化改写，用于给用户做“修改前/修改后”对比。
只返回 JSON：
{
  "rewrittenText":"改写后的文本，保留事实、公式、题目条件，不编造资料",
  "rationale":"简要说明为什么这样改",
  "safetyNotes":["保留了哪些事实/边界"],
  "replaceable":true
}
要求：
1. 只优化表达、层级结构、教学顺序、例子密度和速成课可读性。
2. 不改变考试范围、事实结论、公式条件和题目条件。
3. 如果用户指出结构问题，可以添加小标题、分组和短列表。
4. 如果有 previousRewrite/refinementComment，说明这是继续修改，应基于上一版和补充意见改进。
5. rewrittenText 只返回可替换进当前课程字段的正文，不要包裹解释性前后缀。
6. 需要分段或列举时必须输出真实换行：小标题单独一行，每个编号/项目单独一行；禁止把“1. ... 2. ... 3. ...”挤在同一行。
7. 不要为了配合旧页面列表而保留空白占位项；系统会把 rewrittenText 自动映射为正文、步骤和易错点结构。
"""
    payload = {
        "selectedText": selected,
        "userComment1": comment,
        "context": safe_context,
        "previousRewrite": previous_rewrite,
        "userComment2": refinement_comment,
        "languageRules": rules_prompt,
    }
    deletion_requested = any(phrase in comment for phrase in ("删除", "删掉", "删去", "去掉", "移除", "不要这段", "不需要这段"))
    if deletion_requested:
        return {
            "feedbackId": feedback_id, "originalText": selected, "rewrittenText": "",
            "rationale": "按你的意见删除当前划选内容。", "safetyNotes": ["只删除当前划选片段，不修改其他段落"],
            "replaceable": True,
            "target": {key: safe_context.get(key) for key in ("taskId", "field", "examPointId", "exampleId", "conceptTitle", "itemIndex", "sectionKind", "sourceArea", "selectionFragments")},
            "createdAt": _now_iso(),
        }
    result = model_json(task_prompt, json.dumps(payload, ensure_ascii=False, indent=2), "")
    if not isinstance(result, dict):
        raise ValueError("改写 Agent 没有返回 JSON 对象")
    rewritten = _clip_text(result.get("rewrittenText"), MAX_CONTEXT_TEXT_LENGTH)
    if not rewritten:
        raise ValueError("改写 Agent 没有返回 rewrittenText")
    return {
        "feedbackId": feedback_id,
        "originalText": selected,
        "rewrittenText": rewritten,
        "rationale": _clip_text(result.get("rationale"), 1000),
        "safetyNotes": result.get("safetyNotes") if isinstance(result.get("safetyNotes"), list) else [],
        "replaceable": bool(result.get("replaceable", True)),
        "target": {
            "taskId": safe_context.get("taskId"),
            "field": safe_context.get("field"),
            "examPointId": safe_context.get("examPointId"),
            "exampleId": safe_context.get("exampleId"),
            "conceptTitle": safe_context.get("conceptTitle"),
            "itemIndex": safe_context.get("itemIndex"),
            "sourceArea": safe_context.get("sourceArea"),
            "selectionFragments": safe_context.get("selectionFragments"),
        },
        "createdAt": _now_iso(),
    }


@_locked_course_feedback
def submit_course_feedback_with_rewrite(
    course_id: str,
    *,
    selected_text: str,
    user_comment: str,
    context: dict[str, Any] | None,
    model_json: JsonModelCall | None = None,
) -> dict[str, Any]:
    result = submit_course_feedback(
        course_id,
        selected_text=selected_text,
        user_comment=user_comment,
        context=context,
        model_json=model_json,
    )
    if model_json is None:
        return result
    try:
        proposal = generate_rewrite_proposal(
            course_id,
            str(result["feedbackId"]),
            selected_text=selected_text,
            user_comment=user_comment,
            context=context,
            model_json=model_json,
        )
        _append_rewrite_attempt(course_id, str(result["feedbackId"]), proposal, user_comment, "previewed")
        result["rewriteProposal"] = proposal
        result.update({"status": "awaiting_confirmation", "feedbackSaved": True, "analysisStatus": result.get("status"), "proposalStatus": "ready", "canRetryProposal": False})
        result["message"] = "课程意见已记录，并已生成当前片段优化建议。"
    except Exception as error:
        error_text = _clip_text(error, 1000)
        def persist_error(entries: list[dict[str, Any]]) -> None:
            feedback = _find_feedback(entries, str(result["feedbackId"]))
            feedback["rewriteError"] = error_text
            feedback["status"] = "analyzed" if feedback.get("analysis") else "analysis_failed"
        _mutate_feedback_entries(course_id, persist_error)
        result.update({"feedbackSaved": True, "analysisStatus": result.get("status"), "proposalStatus": "failed", "rewriteError": error_text, "canRetryProposal": True})
        result["message"] = "反馈已保存，但修改建议生成失败。"
    return result


def _find_feedback(entries: list[dict[str, Any]], feedback_id: str) -> dict[str, Any]:
    for entry in entries:
        if entry.get("id") == feedback_id:
            return entry
    raise ValueError("反馈记录不存在")


@_locked_course_feedback
def _append_rewrite_attempt(course_id: str, feedback_id: str, proposal: dict[str, Any], input_comment: str, status: str) -> None:
    # Keep the service read/write seams for existing callers and tests; the default implementations
    # delegate to the per-course locked store.
    entries = _read_feedback_entries(course_id)
    feedback = _find_feedback(entries, feedback_id)
    if feedback.get("status") in TERMINAL_FEEDBACK_STATUSES:
        raise ValueError("反馈会话已结束，不能继续修改")
    session = feedback.setdefault("rewriteSession", {"status": "open", "attempts": []})
    attempts = session.setdefault("attempts", [])
    if len(attempts) >= MAX_SESSION_ATTEMPTS:
        raise ValueError("同一反馈最多可修改 8 轮，请开始新的反馈会话")
    attempts.append({"version": len(attempts) + 1, "inputComment": _clip_text(input_comment, MAX_USER_COMMENT_LENGTH), "rewrittenText": proposal.get("rewrittenText", ""), "rationale": proposal.get("rationale", ""), "accepted": False, "createdAt": _now_iso()})
    session.update({"status": "open", "phase": status, "latestProposal": proposal, "updatedAt": _now_iso()})
    feedback.update({"status": "awaiting_confirmation", "rewriteError": ""})
    _write_feedback_entries(course_id, entries)


@_locked_course_feedback
def retry_course_feedback_proposal(course_id: str, feedback_id: str, *, model_json: JsonModelCall) -> dict[str, Any]:
    feedback = _find_feedback(_read_feedback_entries(course_id), feedback_id)
    if feedback.get("status") in TERMINAL_FEEDBACK_STATUSES:
        raise ValueError("反馈会话已结束，不能重试")
    proposal = generate_rewrite_proposal(course_id, feedback_id, selected_text=str(feedback.get("selectedText") or ""), user_comment=str(feedback.get("userComment") or ""), context=feedback.get("context") if isinstance(feedback.get("context"), dict) else {}, model_json=model_json)
    _append_rewrite_attempt(course_id, feedback_id, proposal, "重试生成修改建议", "retry_previewed")
    return {"feedbackId": feedback_id, "status": "awaiting_confirmation", "proposalStatus": "ready", "rewriteProposal": proposal, "canRetryProposal": False}


@_locked_course_feedback
def abandon_course_feedback(course_id: str, feedback_id: str) -> dict[str, Any]:
    def mutation(entries: list[dict[str, Any]]) -> None:
        feedback = _find_feedback(entries, feedback_id)
        if feedback.get("status") == "accepted":
            raise ValueError("已应用的反馈不能放弃")
        feedback["status"] = "abandoned"
        session = feedback.setdefault("rewriteSession", {"attempts": []})
        session.update({"status": "abandoned", "abandonedAt": _now_iso()})
        _compact_feedback_session(feedback)
    _mutate_feedback_entries(course_id, mutation)
    feedback = _find_feedback(_read_feedback_entries(course_id), feedback_id)
    _activate_feedback_preference(course_id, feedback, False)
    return {"feedbackId": feedback_id, "status": "abandoned", "message": "已放弃本次修改建议。"}


@_locked_course_feedback
def refine_course_feedback_rewrite(
    course_id: str,
    feedback_id: str,
    *,
    extra_comment: str,
    previous_rewrite: str,
    model_json: JsonModelCall,
) -> dict[str, Any]:
    entries = _read_feedback_entries(course_id)
    feedback = _find_feedback(entries, feedback_id)
    session = feedback.get("rewriteSession") if isinstance(feedback.get("rewriteSession"), dict) else {}
    latest = session.get("latestProposal") if isinstance(session.get("latestProposal"), dict) else {}
    authoritative_previous = str(latest.get("rewrittenText") or "")
    if not latest:
        raise ValueError("找不到服务端保存的修改建议")
    proposal = generate_rewrite_proposal(
        course_id,
        feedback_id,
        selected_text=str(feedback.get("selectedText", "")),
        user_comment=str(feedback.get("userComment", "")),
        context=feedback.get("context") if isinstance(feedback.get("context"), dict) else {},
        model_json=model_json,
        previous_rewrite=authoritative_previous,
        refinement_comment=extra_comment,
    )
    _append_rewrite_attempt(course_id, feedback_id, proposal, extra_comment, "refining")
    return {"feedbackId": feedback_id, "rewriteProposal": proposal}


def _replace_text(original: str, selected: str, rewritten: str) -> str:
    if original == selected:
        return rewritten
    if selected and selected in original:
        return original.replace(selected, rewritten, 1)
    raise ValueError("当前内容已经变化，找不到原始选中文本，请刷新后重新选择")


def _try_replace_text(original: str, selected: str, rewritten: str) -> str | None:
    if original == selected:
        return rewritten
    if selected and selected in original:
        return original.replace(selected, rewritten, 1)
    return None


def _replace_in_list(items: list[Any], index: Any, selected: str, rewritten: str) -> bool:
    try:
        idx = int(index)
    except (TypeError, ValueError):
        raise ValueError("缺少列表项定位，无法安全替换")
    if idx < 0 or idx >= len(items) or not isinstance(items[idx], str):
        raise ValueError("列表项定位无效，无法安全替换")
    replaced = _try_replace_text(items[idx], selected, rewritten)
    if replaced is None:
        return False
    items[idx] = replaced
    return True


def _replace_story_section(guide: dict[str, Any], target: dict[str, Any], selected: str, rewritten: str) -> bool:
    field = str(target.get("field") or "")
    section_kind = str(target.get("sectionKind") or "")
    fragments = target.get("selectionFragments") if isinstance(target.get("selectionFragments"), list) else []
    if not section_kind and fragments:
        section_kind = str(next((item.get("sectionKind") for item in fragments if isinstance(item, dict) and item.get("sectionKind")), ""))
    if not field.startswith("storySection.") or not section_kind:
        return False
    key = field.split(".", 1)[1]
    for section in guide.get("sections", []) if isinstance(guide.get("sections"), list) else []:
        if not isinstance(section, dict) or str(section.get("kind")) != section_kind:
            continue
        value = section.get(key)
        if isinstance(value, list) and fragments and rewritten == "":
            indexed: list[tuple[int, str]] = []
            for fragment in fragments:
                if not isinstance(fragment, dict) or str(fragment.get("field")) != field:
                    continue
                try:
                    index = int(fragment.get("itemIndex"))
                except (TypeError, ValueError):
                    return False
                fragment_text = str(fragment.get("selectedText") or "")
                if index < 0 or index >= len(value) or not isinstance(value[index], str) or fragment_text not in value[index]:
                    return False
                indexed.append((index, fragment_text))
            if not indexed:
                return False
            for index, _fragment_text in sorted(indexed, reverse=True):
                del value[index]
            return True
        if isinstance(value, list):
            replaced = _replace_in_list(value, target.get("itemIndex"), selected, rewritten)
            if replaced and rewritten == "":
                value[:] = [item for item in value if item != ""]
            return replaced
        if isinstance(value, str):
            replacement = _try_replace_text(value, selected, rewritten)
            if replacement is not None:
                section[key] = replacement
                return True
    return False


def _replace_exam_point(guide: dict[str, Any], target: dict[str, Any], selected: str, rewritten: str) -> bool:
    field = str(target.get("field") or "")
    point_id = str(target.get("examPointId") or "")
    containers = []
    if isinstance(guide.get("examPoints"), list):
        containers.append(guide.get("examPoints"))
    for section in guide.get("sections", []) if isinstance(guide.get("sections"), list) else []:
        if isinstance(section, dict) and isinstance(section.get("examPoints"), list):
            containers.append(section.get("examPoints"))
    for points in containers:
        for point in points:
            if not isinstance(point, dict) or (point_id and str(point.get("id")) != point_id):
                continue
            if field == "examPoint.explanation":
                replaced = _try_replace_text(str(point.get("explanation", "")), selected, rewritten)
                if replaced is None:
                    continue
                point["explanation"] = replaced
                return True
            if field == "examPoint.title":
                replaced = _try_replace_text(str(point.get("title", "")), selected, rewritten)
                if replaced is None:
                    continue
                point["title"] = replaced
                return True
            if field == "examPoint.procedure" and isinstance(point.get("procedure"), list):
                if _replace_in_list(point["procedure"], target.get("itemIndex"), selected, rewritten):
                    return True
                continue
            if field == "examPoint.pitfalls" and isinstance(point.get("pitfalls"), list):
                if _replace_in_list(point["pitfalls"], target.get("itemIndex"), selected, rewritten):
                    return True
                continue
    return False


def _replace_worked_example(guide: dict[str, Any], target: dict[str, Any], selected: str, rewritten: str) -> bool:
    field = str(target.get("field") or "")
    example_id = str(target.get("exampleId") or "")
    containers = []
    if isinstance(guide.get("workedExamples"), list):
        containers.append(guide.get("workedExamples"))
    for section in guide.get("sections", []) if isinstance(guide.get("sections"), list) else []:
        if isinstance(section, dict) and isinstance(section.get("workedExamples"), list):
            containers.append(section.get("workedExamples"))
    for examples in containers:
        for index, example in enumerate(examples):
            if not isinstance(example, dict):
                continue
            current_id = str(example.get("id") or f"example-{index}")
            if example_id and current_id != example_id:
                continue
            key = field.split(".")[-1]
            if field in {"workedExample.problem", "workedExample.analysis", "workedExample.answer"}:
                fallback = "setup" if key == "problem" and "problem" not in example else ("conclusion" if key == "answer" and "answer" not in example else key)
                replaced = _try_replace_text(str(example.get(fallback, "")), selected, rewritten)
                if replaced is None:
                    continue
                example[fallback] = replaced
                return True
            if field in {"workedExample.steps", "workedExample.checks"} and isinstance(example.get(key), list):
                if _replace_in_list(example[key], target.get("itemIndex"), selected, rewritten):
                    return True
                continue
    return False


def _replace_concept(guide: dict[str, Any], target: dict[str, Any], selected: str, rewritten: str) -> bool:
    if str(target.get("field") or "") != "concept.body":
        return False
    concept_title = str(target.get("conceptTitle") or "")
    containers = []
    if isinstance(guide.get("concepts"), list):
        containers.append(guide.get("concepts"))
    for section in guide.get("sections", []) if isinstance(guide.get("sections"), list) else []:
        if isinstance(section, dict) and isinstance(section.get("concepts"), list):
            containers.append(section.get("concepts"))
    for concepts in containers:
        for concept in concepts:
            if not isinstance(concept, dict) or (concept_title and str(concept.get("title")) != concept_title):
                continue
            replaced = _try_replace_text(str(concept.get("body", "")), selected, rewritten)
            if replaced is None:
                continue
            concept["body"] = replaced
            return True
    return False




def _split_rewrite_sections(rewritten: str) -> dict[str, Any]:
    text = str(rewritten or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    # JSON model output often contains structurally meaningful headings/numbers but no literal
    # newlines. Recover those boundaries before mapping the rewrite back to the study-guide schema.
    text = re.sub(r"(?<!^)(?=【[^】]{1,30}】)", "\n", text)
    # Accept common model numbering variants, including ASCII/full-width punctuation, Chinese
    # parentheses and circled digits. The marker itself is discarded because the renderer owns it.
    marker = r"(?:\d{1,2}[.．、，,、:：)]|[（(]\d{1,2}[）)]|[①②③④⑤⑥⑦⑧⑨⑩])"
    text = re.sub(rf"(?<!^)(?<!\n)(?={marker}\s*)", "\n", text)
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    has_heading = any(re.fullmatch(r"【([^】]+)】[：:]?", line) for line in raw_lines)
    has_list_marker = any(re.match(rf"^{marker}\s*", line) for line in raw_lines)
    result: dict[str, Any] = {"explanation": [], "procedure": [], "pitfalls": []}
    section = "explanation"
    # A numbered rewrite without explicit headings is still a list, not one giant paragraph.
    implicit_list_section = "procedure" if has_list_marker and not has_heading else "explanation"
    for line in raw_lines:
        heading = re.fullmatch(r"【([^】]+)】[：:]?", line)
        if heading:
            title = heading.group(1)
            if re.search(r"易错|误区|注意|陷阱", title):
                section = "pitfalls"
            elif re.search(r"做题|判断|步骤|方法|怎么", title):
                section = "procedure"
            else:
                result["explanation"].append(line)
            continue
        is_list_item = bool(re.match(rf"^(?:[-•*]\s*|{marker}\s*)", line))
        cleaned = re.sub(rf"^(?:[-•*]\s*|{marker}\s*)", "", line).strip()
        if cleaned:
            destination = implicit_list_section if section == "explanation" and is_list_item else section
            result[destination].append(cleaned)
    result["explanation"] = "\n".join(result["explanation"]).strip()
    return result


def _apply_exam_point_rewrite_layout(guide: dict[str, Any], fragments: list[Any], rewritten: str) -> None:
    valid = [item for item in fragments if isinstance(item, dict)]
    point_ids = {str(item.get("examPointId") or "") for item in valid}
    fields = {str(item.get("field") or "") for item in valid}
    if len(point_ids) != 1 or "" in point_ids or not fields.intersection({"examPoint.explanation", "examPoint.procedure", "examPoint.pitfalls"}):
        return
    parsed = _split_rewrite_sections(rewritten)
    if not parsed["procedure"] and not parsed["pitfalls"]:
        return
    point_id = next(iter(point_ids))
    points = guide.get("examPoints") if isinstance(guide.get("examPoints"), list) else []
    point = next((item for item in points if isinstance(item, dict) and str(item.get("id")) == point_id), None)
    if not point:
        return
    explanation = str(point.get("explanation", ""))
    if rewritten in explanation:
        point["explanation"] = explanation.replace(rewritten, parsed["explanation"], 1).strip()
    elif parsed["explanation"]:
        point["explanation"] = parsed["explanation"]
    # The rewrite was temporarily inserted into the first selected field. Remove that carrier item
    # before appending parsed entries, otherwise the page shows an outer “1.” containing the whole
    # rewrite plus the newly split 1/2/3 underneath.
    existing_procedure = [
        str(item).strip() for item in point.get("procedure", [])
        if str(item).strip() and rewritten not in str(item)
    ]
    existing_pitfalls = [
        str(item).strip() for item in point.get("pitfalls", [])
        if str(item).strip() and rewritten not in str(item)
    ]
    point["procedure"] = parsed["procedure"] + existing_procedure
    point["pitfalls"] = parsed["pitfalls"] + existing_pitfalls


def _replace_selection_fragments(guide: dict[str, Any], target: dict[str, Any], selected: str, rewritten: str) -> bool:
    fragments = target.get("selectionFragments")
    if not isinstance(fragments, list) or len(fragments) < 2:
        return False

    # The browser records every intersected structured field in DOM order. Verify that these
    # fragments really reconstruct the submitted selection before touching the workspace.
    compact = lambda value: re.sub(r"\s+", "", str(value or ""))
    joined = "".join(compact(item.get("selectedText")) for item in fragments if isinstance(item, dict))
    if not joined or joined != compact(selected):
        return False

    import copy
    candidate = copy.deepcopy(guide)
    for index, fragment in enumerate(fragments):
        if not isinstance(fragment, dict):
            return False
        fragment_text = _clip_text(fragment.get("selectedText"), MAX_SELECTED_TEXT_LENGTH)
        fragment_target = {**target, **fragment, "selectionFragments": None}
        replacement = rewritten if index == 0 else ""
        replaced = (
            _replace_exam_point(candidate, fragment_target, fragment_text, replacement)
            or _replace_worked_example(candidate, fragment_target, fragment_text, replacement)
            or _replace_concept(candidate, fragment_target, fragment_text, replacement)
        )
        if not replaced:
            return False
    # Keep the replacement in the exact selected field. A pitfalls selection must never be
    # reclassified into explanation/procedure merely because the model returned a heading or a
    # numbered list. Rebuild the selected list from the accepted rewrite and remove only the
    # explicitly anchored source items.
    fields = {str(item.get("field") or "") for item in fragments if isinstance(item, dict)}
    if len(fields) == 1 and next(iter(fields)) in {"examPoint.procedure", "examPoint.pitfalls"}:
        field = next(iter(fields))
        point_id = str(next(item for item in fragments if isinstance(item, dict)).get("examPointId") or "")
        point = next((item for item in candidate.get("examPoints", []) if isinstance(item, dict) and str(item.get("id")) == point_id), None)
        if not point:
            return False
        key = "procedure" if field.endswith("procedure") else "pitfalls"
        parsed = _split_rewrite_sections(rewritten)
        parsed_items = parsed[key] or parsed["pitfalls"] or parsed["procedure"]
        heading = parsed["explanation"].strip()
        if heading and parsed_items:
            parsed_items[0] = f"{heading}\n{parsed_items[0]}"
        elif heading:
            parsed_items = [heading]
        indices = sorted({int(item.get("itemIndex")) for item in fragments if isinstance(item, dict) and str(item.get("itemIndex", "")).isdigit()})
        original_items = guide.get("examPoints", [])
        original_point = next((item for item in original_items if isinstance(item, dict) and str(item.get("id")) == point_id), None)
        if not original_point or any(index >= len(original_point.get(key, [])) for index in indices):
            return False
        source = list(original_point.get(key, []))
        first = indices[0]
        point[key] = source[:first] + parsed_items + [value for index, value in enumerate(source[first:], start=first) if index not in indices]
    else:
        _apply_exam_point_rewrite_layout(candidate, fragments, rewritten)
    guide.clear()
    guide.update(candidate)
    return True


def _replace_first_string_recursive(node: Any, selected: str, rewritten: str) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and selected in value:
                node[key] = _replace_text(value, selected, rewritten)
                return True
            if isinstance(value, (dict, list)) and _replace_first_string_recursive(value, selected, rewritten):
                return True
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str) and selected in value:
                node[index] = _replace_text(value, selected, rewritten)
                return True
            if isinstance(value, (dict, list)) and _replace_first_string_recursive(value, selected, rewritten):
                return True
    return False


def _normalized_visible_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(value or "")).lower()


def _selection_covers_story_text(selected: str, stored: str) -> bool:
    """Match browser-visible text even when formula rendering changes punctuation or spacing."""
    needle = _normalized_visible_text(selected)
    haystack = _normalized_visible_text(stored)
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    prefix = 0
    while prefix < min(len(needle), len(haystack)) and needle[prefix] == haystack[prefix]:
        prefix += 1
    suffix = 0
    while suffix < min(len(needle) - prefix, len(haystack) - prefix) and needle[-(suffix + 1)] == haystack[-(suffix + 1)]:
        suffix += 1
    return (prefix + suffix) / max(len(needle), len(haystack)) >= 0.9


def _replace_scope_fallback(guide: dict[str, Any], target: dict[str, Any], selected: str, rewritten: str) -> bool:
    """Fallback for selections that cross child elements and therefore lack field-level定位.

    The preferred path still uses data-course-feedback-field. When a selection spans several
    rendered children under the same concept/example card, we replace the nearest structured
    block conservatively instead of refusing the user action.
    """
    source_area = str(target.get("sourceArea") or "")
    if source_area.startswith("story_"):
        section_kind = source_area.removeprefix("story_")
        sections = guide.get("sections") if isinstance(guide.get("sections"), list) else []
        matches = [
            section for section in sections
            if isinstance(section, dict)
            and str(section.get("kind")) == section_kind
            and _selection_covers_story_text(selected, str(section.get("narrative", "")))
        ]
        if len(matches) == 1:
            matches[0]["narrative"] = rewritten
            return True
    point_id = str(target.get("examPointId") or "")
    example_id = str(target.get("exampleId") or "")
    if point_id and source_area in {"lesson_explanation", "exam_focus", "unknown"}:
        containers = []
        if isinstance(guide.get("examPoints"), list):
            containers.append(guide.get("examPoints"))
        for section in guide.get("sections", []) if isinstance(guide.get("sections"), list) else []:
            if isinstance(section, dict) and isinstance(section.get("examPoints"), list):
                containers.append(section.get("examPoints"))
        matched = False
        replaced_any = False
        for points in containers:
            for point in points:
                if not isinstance(point, dict) or str(point.get("id")) != point_id:
                    continue
                matched = True
                if _replace_first_string_recursive(point, selected, rewritten):
                    replaced_any = True
                else:
                    # Cross-field selection inside one exam point: collapse the selected teaching block
                    # into explanation while preserving title/formulas/source metadata.
                    point["explanation"] = rewritten
                    point["procedure"] = []
                    point["pitfalls"] = []
                    replaced_any = True
        if matched:
            return replaced_any
    if example_id and source_area in {"worked_example", "unknown"}:
        containers = []
        if isinstance(guide.get("workedExamples"), list):
            containers.append(guide.get("workedExamples"))
        for section in guide.get("sections", []) if isinstance(guide.get("sections"), list) else []:
            if isinstance(section, dict) and isinstance(section.get("workedExamples"), list):
                containers.append(section.get("workedExamples"))
        for examples in containers:
            for index, example in enumerate(examples):
                current_id = str(example.get("id") or f"example-{index}") if isinstance(example, dict) else ""
                if isinstance(example, dict) and current_id == example_id:
                    if _replace_first_string_recursive(example, selected, rewritten):
                        return True
                    example["analysis"] = rewritten
                    return True
    return _replace_first_string_recursive(guide, selected, rewritten)


@_locked_course_feedback
def apply_course_feedback_rewrite(
    course_id: str,
    feedback_id: str,
    *,
    target: dict[str, Any] | None = None,
    original_text: str = "",
    rewritten_text: str = "",
    remember_preference: bool = True,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    from .study_service import _build_study_guide_sections, load_workspace, save_workspace

    entries = _read_feedback_entries(course_id)
    feedback = _find_feedback(entries, feedback_id)
    session = feedback.get("rewriteSession") if isinstance(feedback.get("rewriteSession"), dict) else {}
    if feedback.get("status") == "accepted" and isinstance(session.get("acceptedRewrite"), dict):
        return {"feedbackId": feedback_id, "workspace": load_workspace(course_id, refresh_materials=False), "status": "accepted", "idempotent": True, "message": "本次修改已应用。"}
    if feedback.get("status") in {"abandoned", "expired"}:
        raise ValueError("反馈会话已结束，不能应用")
    proposal = session.get("latestProposal") if isinstance(session.get("latestProposal"), dict) else None
    if not proposal:
        raise ValueError("找不到服务端保存的修改建议")
    selected = _clip_text(proposal.get("originalText"), MAX_SELECTED_TEXT_LENGTH)
    rewritten = _clip_text(proposal.get("rewrittenText"), MAX_CONTEXT_TEXT_LENGTH)
    if proposal.get("rewrittenText") != "" and not rewritten:
        raise ValueError("服务端修改建议内容无效")
    authoritative_target = proposal.get("target") if isinstance(proposal.get("target"), dict) else {}
    target = dict(authoritative_target)
    task_id = str(target.get("taskId") or "")
    workspace = load_workspace(course_id, refresh_materials=False)
    loaded_revision = int(workspace.get("revision", 0))
    if expected_revision is not None and expected_revision != loaded_revision:
        raise RuntimeError("学习空间已被其他操作更新，请刷新后重试")
    if not task_id:
        # 兼容修复前已经打开的反馈弹窗：旧故事页没有 taskId，但字段、章节和原文锚点仍然存在。
        # 只在课程中恰好一个任务匹配时补全，避免把内容误删到另一课。
        inferred: list[str] = []
        field = str(target.get("field") or "")
        section_kind = str(target.get("sectionKind") or "")
        for candidate in workspace.get("tasks", []):
            if not isinstance(candidate, dict) or not isinstance(candidate.get("studyGuide"), dict):
                continue
            guide_candidate = candidate["studyGuide"]
            if field.startswith("storySection.") and section_kind:
                key = field.split(".", 1)[1]
                for section in guide_candidate.get("sections", []) if isinstance(guide_candidate.get("sections"), list) else []:
                    if not isinstance(section, dict) or str(section.get("kind")) != section_kind:
                        continue
                    value = section.get(key)
                    haystack = "\n".join(str(item) for item in value) if isinstance(value, list) else str(value or "")
                    if selected and selected.replace("\n", "") in haystack.replace("\n", ""):
                        inferred.append(str(candidate.get("id") or ""))
            elif selected and selected in json.dumps(guide_candidate, ensure_ascii=False):
                inferred.append(str(candidate.get("id") or ""))
        inferred = list(dict.fromkeys(item for item in inferred if item))
        if len(inferred) != 1:
            raise ValueError("缺少任务定位，且无法从当前选区唯一确认所属课程小节。请关闭弹窗后重新划选。")
        task_id = inferred[0]
        target["taskId"] = task_id
    task = next((item for item in workspace.get("tasks", []) if isinstance(item, dict) and str(item.get("id")) == task_id), None)
    if not task:
        raise ValueError("找不到当前学习任务")
    guide = task.get("studyGuide") if isinstance(task.get("studyGuide"), dict) else None
    if guide is None:
        raise ValueError("当前任务没有可替换的讲义内容")
    replaced = (
        _replace_selection_fragments(guide, target, selected, rewritten)
        or _replace_story_section(guide, target, selected, rewritten)
        or _replace_exam_point(guide, target, selected, rewritten)
        or _replace_worked_example(guide, target, selected, rewritten)
        or _replace_concept(guide, target, selected, rewritten)
        or _replace_scope_fallback(guide, target, selected, rewritten)
    )
    if not replaced:
        raise ValueError("无法根据当前选区的结构锚点确认唯一替换位置。课程内容可能已变化，请重新划选后再试。")
    # Rebuild only this guide's rendered mirror from its canonical fields. Do not run the global
    # workspace quality migrator here: accepting a local wording change must never normalize or
    # rewrite unrelated examples, questions, or other tasks.
    guide["sections"] = _build_study_guide_sections(guide)
    task["contentUpdatedAt"] = _now_iso()
    save_workspace(workspace, course_id, expected_revision=loaded_revision)

    entries = _read_feedback_entries(course_id)
    feedback = _find_feedback(entries, feedback_id)
    session = feedback.setdefault("rewriteSession", {"status": "accepted", "attempts": []})
    session["status"] = "accepted"
    session["acceptedAt"] = _now_iso()
    session["acceptedRewrite"] = {"originalText": selected, "rewrittenText": rewritten, "target": target, "acceptedAt": _now_iso()}
    attempts = session.get("attempts") if isinstance(session.get("attempts"), list) else []
    if attempts:
        attempts[-1]["accepted"] = True
        session["acceptedVersion"] = attempts[-1].get("version")
    feedback["status"] = "accepted"
    feedback["rememberPreference"] = bool(remember_preference)
    _compact_feedback_session(feedback)
    _write_feedback_entries(course_id, entries)
    _activate_feedback_preference(course_id, feedback, remember_preference)
    return {"feedbackId": feedback_id, "workspace": workspace, "status": "accepted", "idempotent": False, "rememberPreference": bool(remember_preference), "message": "已替换当前课程内容，并记录本次确认结果。"}

def _guide_revision_token(guide: dict[str, Any]) -> str:
    import hashlib
    encoded = json.dumps(guide, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def _resolve_guide_section(guide: dict[str, Any], section_id: str, section_index: int) -> tuple[int, dict[str, Any]]:
    from .study_service import _build_study_guide_sections
    sections = _build_study_guide_sections(guide)
    for index, section in enumerate(sections):
        if isinstance(section, dict) and str(section.get("id") or section.get("kind") or "") == section_id:
            return index, section
    if 0 <= section_index < len(sections) and isinstance(sections[section_index], dict):
        return section_index, sections[section_index]
    raise ValueError("找不到当前课程小节")


def _apply_revised_guide_section(guide: dict[str, Any], section_id: str, section_index: int, revised: dict[str, Any]) -> None:
    sections = guide.get("sections") if isinstance(guide.get("sections"), list) else []
    is_story = isinstance(guide.get("storyContext"), dict) and any(isinstance(item, dict) and item.get("kind") for item in sections)
    if is_story:
        index, _current = _resolve_guide_section(guide, section_id, section_index)
        next_section = json.loads(json.dumps(revised, ensure_ascii=False))
        next_section["kind"] = sections[index].get("kind")
        sections[index] = next_section
        return
    canonical_keys = {
        "exam-focus": ("planningReason", "objectives", "sourceHighlights", "examPoints"),
        "method": ("examPoints", "concepts"),
        "worked-example": ("example", "workedExamples"),
        "self-check": ("checklist", "selfTestQuestionIds"),
    }
    resolved_id = section_id if section_id in canonical_keys else ("exam-focus", "method", "worked-example", "self-check")[section_index] if 0 <= section_index < 4 else ""
    if not resolved_id:
        raise ValueError("当前小节定位无效")
    for key in canonical_keys[resolved_id]:
        if key in revised:
            guide[key] = json.loads(json.dumps(revised[key], ensure_ascii=False))


@_locked_course_feedback
def submit_global_course_feedback(
    course_id: str, *, task_id: str, section_id: str, section_index: int, user_comment: str, model_json: JsonModelCall,
) -> dict[str, Any]:
    """Create a revision proposal for one of the four lesson subsections."""
    from .study_service import load_workspace
    comment = _clip_text(user_comment, MAX_USER_COMMENT_LENGTH)
    if not comment:
        raise ValueError("请填写小节修改要求")
    workspace = load_workspace(course_id, refresh_materials=False)
    task = next((item for item in workspace.get("tasks", []) if isinstance(item, dict) and str(item.get("id")) == task_id), None)
    if not task or not isinstance(task.get("studyGuide"), dict):
        raise ValueError("当前任务没有可修改的讲义内容")
    guide = task["studyGuide"]
    resolved_index, current_section = _resolve_guide_section(guide, section_id, section_index)
    resolved_id = str(current_section.get("id") or current_section.get("kind") or section_id)
    section_label = str(current_section.get("label") or f"第 {resolved_index + 1} 小节")
    feedback_id = f"cfb_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    feedback = {
        "id": feedback_id, "courseId": course_id,
        "selectedText": f"课程小节：{task.get('title')} · {section_label}", "userComment": comment,
        "context": _safe_context({"taskId": task_id, "taskTitle": task.get("title"), "sectionId": resolved_id, "sectionIndex": resolved_index, "sectionLabel": section_label, "sourceArea": "global_section", "feedbackScope": "section", "operation": "revise_lesson_section", "anchor": "current_section"}),
        "createdAt": _now_iso(), "status": "pending_analysis", "analysis": None, "analysisError": "",
    }
    entries = _read_feedback_entries(course_id); entries.append(feedback); _write_feedback_entries(course_id, entries)
    task_prompt = """
你同时是 Lesson Section Revision Agent 和 Course Feedback Analyst。只修改当前课程的一个小节，不得改动另外三个小节；并把用户意见提炼成一条可复用的课程优化规则。
只返回 JSON：
{"revisedSection":{"保持当前小节字段结构并完成修改":"..."},"changeSummary":"简短摘要","rationale":"修改理由","analysis":{"problemTypes":["other"],"diagnosis":"问题诊断","suggestedRewrite":"简短示例","ruleCandidate":{"type":"teaching_style|teaching_order|example_density|tone|exam_orientation|other","title":"短标题","description":"规则说明","badPattern":"应避免模式","preferredPattern":"以后应采用的模式"}}}
要求：revisedSection 必须是完整的小节对象；保留事实、公式和题目条件；保持字段类型；不要返回整篇 studyGuide；排版修复应保留原内容，只修正层级、段落、列表和公式呈现；只输出 JSON。
"""
    payload = {"task": {"id": task_id, "title": task.get("title")}, "section": {"id": resolved_id, "index": resolved_index, "content": current_section}, "userComment": comment, "languageRules": get_course_feedback_rules_prompt(course_id)}
    try:
        generated = model_json(task_prompt, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "")
        revised = generated.get("revisedSection") if isinstance(generated, dict) else None
        analysis = generated.get("analysis") if isinstance(generated, dict) else None
        if not isinstance(revised, dict) or not revised: raise ValueError("小节修改 Agent 没有返回完整 revisedSection")
        if not isinstance(analysis, dict) or not isinstance(analysis.get("ruleCandidate"), dict): raise ValueError("小节修改 Agent 没有返回优化规则分析")
        entries = _read_feedback_entries(course_id); feedback = _find_feedback(entries, feedback_id)
        feedback["status"] = "analyzed"; feedback["analysis"] = analysis
        store = _read_rules_store(course_id); store["rules"] = _merge_rule(store.get("rules", []), analysis["ruleCandidate"], feedback_id); store["strongDirectives"] = _merge_strong_directive(store.get("strongDirectives", []), feedback); store["summaryPrompt"] = _build_summary_prompt(store["rules"]); _write_rules_store(course_id, store); _write_feedback_entries(course_id, entries)
        proposal = {"feedbackId": feedback_id, "taskId": task_id, "taskTitle": str(task.get("title") or "当前课程"), "sectionId": resolved_id, "sectionIndex": resolved_index, "sectionLabel": section_label, "changeSummary": _clip_text(generated.get("changeSummary") or "已生成当前小节修改方案", 1000), "rationale": _clip_text(generated.get("rationale"), 1000), "revisedSection": revised, "baseRevision": _guide_revision_token(guide), "createdAt": _now_iso()}
        _append_rewrite_attempt(course_id, feedback_id, proposal, comment, "section_previewed")
        return {"feedbackId": feedback_id, "status": "analyzed", "message": "小节意见已记录，并已生成当前小节修改预览。", "proposal": proposal}
    except Exception as error:
        entries = _read_feedback_entries(course_id); feedback = _find_feedback(entries, feedback_id); feedback["globalRewriteError"] = str(error); feedback["analysisError"] = str(error); _write_feedback_entries(course_id, entries); raise


@_locked_course_feedback
def refine_global_course_feedback(
    course_id: str, feedback_id: str, *, extra_comment: str, model_json: JsonModelCall,
) -> dict[str, Any]:
    """Refine the latest section proposal while retaining the same feedback session."""
    from .study_service import load_workspace

    comment = _clip_text(extra_comment, MAX_USER_COMMENT_LENGTH)
    if not comment:
        raise ValueError("请填写希望继续调整的要求")
    entries = _read_feedback_entries(course_id)
    feedback = _find_feedback(entries, feedback_id)
    session = feedback.get("rewriteSession") if isinstance(feedback.get("rewriteSession"), dict) else {}
    previous = session.get("latestProposal") if isinstance(session.get("latestProposal"), dict) else None
    if not previous or not isinstance(previous.get("revisedSection"), dict):
        raise ValueError("找不到可继续修改的小节方案")

    workspace = load_workspace(course_id, refresh_materials=False)
    task_id = str(previous.get("taskId") or "")
    task = next((item for item in workspace.get("tasks", []) if isinstance(item, dict) and str(item.get("id")) == task_id), None)
    if not task or not isinstance(task.get("studyGuide"), dict):
        raise ValueError("当前任务没有可修改的讲义内容")
    guide = task["studyGuide"]
    if _guide_revision_token(guide) != str(previous.get("baseRevision") or ""):
        raise RuntimeError("课程内容已发生变化，请重新发起小节修改")

    attempts = session.get("attempts") if isinstance(session.get("attempts"), list) else []
    conversation = [
        {"role": "user", "content": str(item.get("inputComment") or "")}
        for item in attempts if isinstance(item, dict) and str(item.get("inputComment") or "").strip()
    ]
    task_prompt = """
你是 Lesson Section Revision Agent。用户正在围绕同一个课程小节进行多轮修改。请在上一版候选小节上继续修改，不得改动另外三个小节。
只返回 JSON：
{"revisedSection":{"保持上一版小节字段结构并完成修改":"..."},"changeSummary":"简短摘要","rationale":"修改理由"}
要求：把本轮意见与历史意见结合，除非用户明确撤销，否则保留前几轮已要求的改动；revisedSection 必须完整；保持字段类型、事实、公式和题目条件；不要返回整篇 studyGuide；只输出 JSON。
"""
    payload = {
        "task": {"id": task_id, "title": task.get("title")},
        "section": {"id": previous.get("sectionId"), "index": previous.get("sectionIndex")},
        "originalSection": _resolve_guide_section(guide, str(previous.get("sectionId") or ""), int(previous.get("sectionIndex") or 0))[1],
        "previousRevisedSection": previous["revisedSection"],
        "conversation": conversation,
        "latestUserComment": comment,
        "languageRules": get_course_feedback_rules_prompt(course_id),
    }
    generated = model_json(task_prompt, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "")
    revised = generated.get("revisedSection") if isinstance(generated, dict) else None
    if not isinstance(revised, dict) or not revised:
        raise ValueError("小节修改 Agent 没有返回完整 revisedSection")
    proposal = {
        **previous,
        "changeSummary": _clip_text(generated.get("changeSummary") or "已根据补充意见更新小节方案", 1000),
        "rationale": _clip_text(generated.get("rationale"), 1000),
        "revisedSection": revised,
        "createdAt": _now_iso(),
    }
    _append_rewrite_attempt(course_id, feedback_id, proposal, comment, "section_refined")
    return {"feedbackId": feedback_id, "status": "analyzed", "message": "已结合对话上下文更新当前小节修改预览。", "proposal": proposal}


@_locked_course_feedback
def apply_global_course_feedback(course_id: str, feedback_id: str, *, remember_preference: bool = True) -> dict[str, Any]:
    from .study_service import _build_study_guide_sections, load_workspace, save_workspace

    entries = _read_feedback_entries(course_id)
    feedback = _find_feedback(entries, feedback_id)
    session = feedback.get("rewriteSession") if isinstance(feedback.get("rewriteSession"), dict) else {}
    if feedback.get("status") == "accepted" and isinstance(session.get("acceptedGlobalRewrite"), dict):
        return {"feedbackId": feedback_id, "workspace": load_workspace(course_id, refresh_materials=False), "status": "accepted", "idempotent": True, "message": "本次小节修改已应用。"}
    if feedback.get("status") in {"abandoned", "expired"}:
        raise ValueError("反馈会话已结束，不能应用")
    proposal = session.get("latestProposal") if isinstance(session.get("latestProposal"), dict) else None
    if not proposal or not isinstance(proposal.get("revisedSection"), dict):
        raise ValueError("找不到可应用的小节修改方案")
    task_id = str(proposal.get("taskId") or "")
    workspace = load_workspace(course_id, refresh_materials=False)
    loaded_revision = int(workspace.get("revision", 0))
    task = next((item for item in workspace.get("tasks", []) if isinstance(item, dict) and str(item.get("id")) == task_id), None)
    if not task or not isinstance(task.get("studyGuide"), dict):
        raise ValueError("当前课程讲义已不存在")
    guide = task["studyGuide"]
    if _guide_revision_token(guide) != str(proposal.get("baseRevision") or ""):
        raise RuntimeError("课程内容已发生变化，请重新生成小节修改方案")
    _apply_revised_guide_section(guide, str(proposal.get("sectionId") or ""), int(proposal.get("sectionIndex") or 0), proposal["revisedSection"])
    guide["sections"] = _build_study_guide_sections(guide)
    task["contentUpdatedAt"] = _now_iso()
    save_workspace(workspace, course_id, expected_revision=loaded_revision)
    accepted_at = _now_iso()
    session["status"] = "accepted"
    session["acceptedAt"] = accepted_at
    session["acceptedGlobalRewrite"] = {"operation": "revise_lesson_section", "anchor": "current_section", "taskId": task_id, "sectionId": proposal.get("sectionId"), "sectionIndex": proposal.get("sectionIndex"), "baseRevision": proposal.get("baseRevision"), "appliedRevision": _guide_revision_token(guide), "changeSummary": proposal.get("changeSummary"), "acceptedAt": accepted_at}
    attempts = session.get("attempts") if isinstance(session.get("attempts"), list) else []
    if attempts:
        attempts[-1]["accepted"] = True
    feedback["status"] = "accepted"
    feedback["rememberPreference"] = remember_preference
    _activate_feedback_preference(course_id, feedback, remember_preference)
    _compact_feedback_session(feedback)
    _write_feedback_entries(course_id, entries)
    return {"feedbackId": feedback_id, "status": "accepted", "message": "已应用当前小节修改。" + ("课程偏好已启用。" if remember_preference else "本次未保存为课程偏好。"), "workspace": workspace}
