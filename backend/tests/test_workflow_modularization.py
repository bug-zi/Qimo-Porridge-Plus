from __future__ import annotations

from app.agents import workflow
from app.agents import content_validation, content_workflow, formula_rules, orientation, question_generation, strategy_workflow


def test_workflow_facade_preserves_public_entrypoints() -> None:
    assert workflow.run_strategy_workflow is strategy_workflow.run_strategy_workflow
    assert workflow.run_content_workflow is content_workflow.run_content_workflow
    assert workflow.build_orientation_guide is orientation.build_orientation_guide
    assert workflow.with_structured_formula_rules is formula_rules.with_structured_formula_rules
    assert workflow._study_guide_issues is content_validation._study_guide_issues
    assert workflow._question_issues is question_generation._question_issues


def test_workflow_contract_versions_remain_stable() -> None:
    assert workflow.FORMULA_OUTPUT_CONTRACT_VERSION == 1
    assert workflow.LESSON_CONTENT_CONTRACT_VERSION == 4
    assert "【统一公式输出规范（适用于所有课程）】" in workflow.STRUCTURED_FORMULA_OUTPUT_RULES


def test_mock_repair_facade_forwards_patched_retrieval(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def retrieval(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return {"context": "patched evidence"}

    monkeypatch.setattr(workflow, "retrieve_material_context", retrieval)

    workspace = {
        "course": {"name": "测试课"},
        "onboarding": {},
        "assessmentProfile": {},
        "knowledgePoints": [{"id": "kp-1", "name": "知识点", "weight": 10, "source": "资料"}],
        "tasks": [],
        "mockQuestions": [],
    }

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("offline")

    result = workflow.repair_mock_questions("course-1", workspace, unavailable)
    assert seen["args"][0] == "course-1"
    assert result["source"] == "fallback"
    assert result["mockQuestions"]


def test_review_plan_renderer_is_compact_and_preserves_topic_order() -> None:
    profile = strategy_workflow.CourseProfile.model_validate(
        {
            "course_name": "测试课",
            "assessment_summary": "",
            "question_types": [],
            "topics": [
                {"id": "chapter-1", "name": "第一章基础", "priority": "low", "exam_value": 20},
                {"id": "chapter-2", "name": "第二章重点", "priority": "high", "exam_value": 95},
            ],
        }
    )
    plan = strategy_workflow.ReviewPlanSpec.model_validate(
        {
            "goal_summary": "内部目标",
            "scope_summary": "先学习第一章基础，再学习第二章重点。",
            "priority_notes": [],
            "days": [
                {
                    "day": 1,
                    "title": "第一章",
                    "goal": "掌握第一章",
                    "rationale": "按资料原序推进",
                    "blocks": [
                        {
                            "minutes": 30,
                            "topic_id": "chapter-1",
                            "topic": "第一章基础",
                            "source": "主资料",
                            "action": "理解定义",
                            "output": "完成两道题",
                            "completion": "正确率达到80%",
                        }
                    ],
                    "must_know": ["基础定义"],
                    "test": "限时完成两道题",
                    "review_rule": "只调整时长",
                }
            ],
            "final_success_criteria": [],
            "adjustment_rules": [],
        }
    )

    rendered = strategy_workflow._render_review_plan(plan, profile)

    assert "## 主线规划" in rendered
    assert "## 知识点与讲解深度" in rendered
    assert "## 每日计划" in rendered
    assert "## 学习目标与时间约束" not in rendered
    assert "## 知识点优先级" not in rendered
    assert "## 总体时间分配" not in rendered
    assert "## 动态调整规则" not in rendered
    assert "简要覆盖" in rendered and "重点详讲" in rendered
    assert rendered.index("第一章基础") < rendered.index("第二章重点")

