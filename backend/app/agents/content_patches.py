from __future__ import annotations

from copy import deepcopy
from typing import Any


_ALLOWED_GUIDE_ROOTS = {"examPoints", "workedExamples", "storyContext", "sections"}
_ALLOWED_QUESTION_FIELDS = {"prompt", "options", "answerIndex", "explanation", "examPointIds", "referenceAnswer", "gradingRubric", "questionType", "score", "type"}
_FORBIDDEN_FIELDS = {"id", "taskId", "knowledgePointId", "source"}


def _segments(path: str) -> list[str | int]:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("patch path 不能为空")
    # 模型常按 JSON Pointer 惯例返回 /sections/0/questions；统一归一化为
    # 点号分隔（sections[0].questions）再解析，两种写法等价接受。
    # 纯数字段重建为方括号下标，否则会被当作 dict 键导致"路径与结构不匹配"。
    normalized = path.strip()
    if normalized.startswith("/"):
        rebuilt = ""
        for segment in normalized.split("/"):
            if not segment:
                continue
            if segment.isdigit():
                rebuilt += f"[{segment}]"
            elif rebuilt:
                rebuilt += f".{segment}"
            else:
                rebuilt = segment
        path = rebuilt
    result: list[str | int] = []
    for part in path.split("."):
        if not part:
            raise ValueError(f"patch path 无效：{path}")
        while "[" in part:
            name, rest = part.split("[", 1)
            if name:
                result.append(name)
            if "]" not in rest:
                raise ValueError(f"patch path 无效：{path}")
            index_text, part = rest.split("]", 1)
            if not index_text.isdigit():
                raise ValueError(f"patch path 下标无效：{path}")
            result.append(int(index_text))
        if part:
            result.append(part)
    if len(result) > 8:
        raise ValueError("patch path 过深")
    return result


def _container(root: Any, parts: list[str | int], *, create: bool = False) -> tuple[Any, str | int]:
    if not parts:
        raise ValueError("patch path 不能为空")
    current = root
    for index, part in enumerate(parts[:-1]):
        if isinstance(current, dict) and isinstance(part, str):
            if part not in current:
                if not create:
                    raise ValueError(f"patch 目标不存在：{part}")
                current[part] = {} if isinstance(parts[index + 1], str) else []
            current = current[part]
        elif isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
            current = current[part]
        else:
            raise ValueError("patch 路径与初稿结构不匹配")
    return current, parts[-1]


def _validate_guide_path(path: str) -> list[str | int]:
    parts = _segments(path)
    if not isinstance(parts[0], str) or parts[0] not in _ALLOWED_GUIDE_ROOTS:
        raise ValueError(f"讲义 patch 不允许修改路径：{path}")
    if any(isinstance(part, str) and part in _FORBIDDEN_FIELDS for part in parts):
        raise ValueError(f"讲义 patch 不允许修改不可变字段：{path}")
    return parts


def _validate_question_path(path: str) -> list[str | int]:
    parts = _segments(path)
    if not isinstance(parts[0], str) or parts[0] not in _ALLOWED_QUESTION_FIELDS:
        raise ValueError(f"自测 patch 不允许修改字段：{path}")
    if any(isinstance(part, str) and part in _FORBIDDEN_FIELDS for part in parts):
        raise ValueError(f"自测 patch 不允许修改不可变字段：{path}")
    return parts


def _apply_one(root: Any, operation: str, parts: list[str | int], value: Any = None) -> None:
    parent, key = _container(root, parts, create=operation == "add")
    if isinstance(parent, dict) and isinstance(key, str):
        if operation == "remove":
            if key not in parent:
                raise ValueError(f"patch 目标不存在：{key}")
            del parent[key]
        elif operation in {"add", "replace"}:
            if operation == "replace" and key not in parent:
                raise ValueError(f"replace 目标不存在：{key}")
            parent[key] = deepcopy(value)
        else:
            raise ValueError(f"不支持的 patch 操作：{operation}")
    elif isinstance(parent, list) and isinstance(key, int):
        if operation == "add" and key == len(parent):
            parent.append(deepcopy(value))
        elif 0 <= key < len(parent):
            if operation == "remove":
                parent.pop(key)
            elif operation in {"add", "replace"}:
                parent[key] = deepcopy(value)
            else:
                raise ValueError(f"不支持的 patch 操作：{operation}")
        else:
            raise ValueError("patch 数组下标越界")
    else:
        raise ValueError("patch 路径与初稿结构不匹配")


def apply_guide_patches(guide: dict[str, Any], payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("patches"), list) or not payload["patches"]:
        raise ValueError("讲义 patch 响应必须包含非空 patches")
    if len(payload["patches"]) > 12:
        raise ValueError("讲义 patch 数量超过上限")
    result = deepcopy(guide)
    for patch in payload["patches"]:
        if not isinstance(patch, dict):
            raise ValueError("讲义 patch 必须是对象")
        operation = str(patch.get("op", ""))
        parts = _validate_guide_path(str(patch.get("path", "")))
        _apply_one(result, operation, parts, patch.get("value"))
    return result


def apply_question_patches(questions: list[dict[str, Any]], payload: Any, task_id: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("patches"), list) or not payload["patches"]:
        raise ValueError("自测 patch 响应必须包含非空 patches")
    if len(payload["patches"]) > 12:
        raise ValueError("自测 patch 数量超过上限")
    result = deepcopy(questions)
    by_id = {str(item.get("id")): item for item in result if isinstance(item, dict)}
    for patch in payload["patches"]:
        if not isinstance(patch, dict):
            raise ValueError("自测 patch 必须是对象")
        if str(patch.get("op", "")) == "add_question":
            question = patch.get("question")
            if not isinstance(question, dict) or not str(question.get("id", "")).strip():
                raise ValueError("新增自测题必须包含 id")
            if str(question.get("taskId", task_id)) != task_id:
                raise ValueError("新增自测题 taskId 不匹配")
            question_id = str(question["id"])
            if question_id in by_id:
                raise ValueError(f"新增自测题 id 重复：{question_id}")
            result.append(deepcopy(question))
            by_id[str(question["id"])] = result[-1]
            continue
        question_id = str(patch.get("questionId", "")).strip()
        target = by_id.get(question_id)
        if target is None:
            raise ValueError(f"自测 patch 找不到题目：{question_id}")
        parts = _validate_question_path(str(patch.get("path", "")))
        _apply_one(target, str(patch.get("op", "")), parts, patch.get("value"))
    return result
