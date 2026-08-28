from __future__ import annotations

import re
from typing import Any


_CONCLUSION_MARKERS = ("正确答案是", "正确答案为", "答案是", "答案为", "应选", "应该选择", "应当选择", "故选", "所以选", "因此选")


def _comparison_text(value: Any) -> str:
    """Normalize display-only syntax while retaining semantic characters."""
    text = str(value or "").lower()
    text = re.sub(r"\\(?:text|mathrm)\s*\{([^{}]*)\}", r"\1", text)
    text = text.replace("\\(", "").replace("\\)", "").replace("$", "")
    return re.sub(r'[\s「」『』“”"\'：:，,。；;！!？?（）()]', "", text)


def explanation_answer_index(question: dict[str, Any]) -> int | None:
    """Infer an option only from an explicit conclusion in the explanation.

    This is intentionally conservative: merely mentioning an option is not
    evidence, and letter-only conclusions (for example, "答案是 C") are
    ignored because option shuffling can make historical letters stale.
    """
    options = question.get("options")
    if not isinstance(options, list) or len(options) < 2:
        return None
    explanation = _comparison_text(question.get("explanation"))
    if not explanation:
        return None

    matches: list[int] = []
    for index, option in enumerate(options):
        normalized_option = _comparison_text(option)
        if not normalized_option or len(normalized_option) == 1 and normalized_option.isalpha():
            continue
        if any(f"{_comparison_text(marker)}{normalized_option}" in explanation for marker in _CONCLUSION_MARKERS):
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def reconcile_question_answer(question: dict[str, Any]) -> bool:
    """Make answerIndex follow an unambiguous explicit explanation conclusion."""
    inferred = explanation_answer_index(question)
    if inferred is None or question.get("answerIndex") == inferred:
        return False
    question["answerIndex"] = inferred
    return True
