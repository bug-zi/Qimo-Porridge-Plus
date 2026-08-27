from __future__ import annotations

"""Backward-compatible facade for the modular Agent workflow implementation.

New code should import from the focused modules. Existing callers may continue to
use app.agents.workflow while integrations migrate incrementally.
"""

from typing import Any

from .content_validation import (
    _deterministic_review,
    _plan_issues,
    _select_missing_lesson_tasks,
    _study_guide_issues,
)
from .checkpoint_contracts import LESSON_CONTENT_CONTRACT_VERSION
from .content_workflow import run_content_workflow
from .formula_rules import (
    FORMULA_OUTPUT_CONTRACT_VERSION,
    STRUCTURED_FORMULA_OUTPUT_RULES,
    with_structured_formula_rules,
)
from .lesson_fallbacks import _backup_practice_questions, _backup_study_guide
from .orientation import (
    ORIENTATION_TASK_ID,
    _backup_orientation_guide,
    _make_orientation_task,
    _orientation_guide_issues,
    build_orientation_guide,
)
from .question_generation import (
    _backup_mock_questions,
    _extract_mock_score_targets,
    _mock_blueprint_from_context,
    _mock_blueprint_issues,
    _mock_question_bucket,
    _question_issues,
    _strong_feedback_issues,
    _shuffle_single_choice_options,
    _shuffle_single_choice_questions,
    _split_scores,
    mock_questions_need_repair,
    repair_mock_questions as _repair_mock_questions,
)
from .strategy_workflow import run_strategy_workflow
from .workflow_types import JsonModelCall
from ..knowledge_service import retrieve_material_context


def repair_mock_questions(
    course_id: str,
    workspace: dict[str, Any],
    model_json: JsonModelCall,
    *,
    course_prompt: str = "",
) -> dict[str, Any]:
    """Compatibility wrapper preserving workflow.retrieve_material_context monkeypatches."""
    return _repair_mock_questions(
        course_id,
        workspace,
        model_json,
        course_prompt=course_prompt,
        retrieve_context=retrieve_material_context,
    )
