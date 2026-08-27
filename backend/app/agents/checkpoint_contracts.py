from __future__ import annotations

import hashlib
import json
from typing import Any


FORMULA_OUTPUT_CONTRACT_VERSION = 1
LESSON_CONTENT_CONTRACT_VERSION = 4
QUESTION_CHECKPOINT_VERSION = 1
MOCK_BLUEPRINT_PROMPT_VERSION = 2
GUIDE_SIGNATURE_PREFIX = "split-guide-v2:"


def stable_signature(payload: Any) -> str:
    """Hash a checkpoint payload using the historical byte-for-byte JSON contract."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def content_plan_signature(
    *,
    course: Any,
    onboarding: Any,
    review_plan: str,
    course_prompt: str,
) -> str:
    return stable_signature(
        {
            "formulaOutputContractVersion": FORMULA_OUTPUT_CONTRACT_VERSION,
            "course": course,
            "onboarding": onboarding,
            "reviewPlan": review_plan,
            "coursePrompt": course_prompt,
        }
    )


def lesson_content_signature(
    *,
    style_contract: Any,
    task: Any,
    review_plan: str,
    course_prompt: str,
) -> str:
    return stable_signature(
        {
            "formulaOutputContractVersion": FORMULA_OUTPUT_CONTRACT_VERSION,
            "lessonContentContractVersion": LESSON_CONTENT_CONTRACT_VERSION,
            "styleContract": style_contract,
            "task": task,
            "reviewPlan": review_plan,
            "coursePrompt": course_prompt,
        }
    )


def lesson_guide_signature(lesson_signature: str) -> str:
    return hashlib.sha256(f"{GUIDE_SIGNATURE_PREFIX}{lesson_signature}".encode("utf-8")).hexdigest()


def lesson_questions_signature(*, lesson_signature: str, exam_points: Any) -> str:
    return stable_signature(
        {
            "version": QUESTION_CHECKPOINT_VERSION,
            "formulaOutputContractVersion": FORMULA_OUTPUT_CONTRACT_VERSION,
            "lessonSignature": lesson_signature,
            "examPoints": exam_points,
        }
    )


def mock_questions_signature(
    *,
    onboarding: Any,
    knowledge_points: Any,
    task_plan: Any,
    review_plan: str,
    course_prompt: str,
) -> str:
    return stable_signature(
        {
            "mockBlueprintPromptVersion": MOCK_BLUEPRINT_PROMPT_VERSION,
            "formulaOutputContractVersion": FORMULA_OUTPUT_CONTRACT_VERSION,
            "onboarding": onboarding,
            "knowledgePoints": knowledge_points,
            "tasks": task_plan,
            "reviewPlan": review_plan,
            "coursePrompt": course_prompt,
        }
    )


def orientation_guide_signature(
    *,
    modules: Any,
    knowledge_points: Any,
    review_plan: str,
    days: int,
) -> str:
    return stable_signature(
        {
            "modules": modules,
            "knowledgePoints": knowledge_points,
            "reviewPlan": review_plan,
            "days": days,
        }
    )
