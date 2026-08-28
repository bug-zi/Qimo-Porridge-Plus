from app.course_style_templates import (
    COURSE_STYLE_TEMPLATES,
    course_style_prompt_context,
    get_course_style_template,
    normalize_course_content_style,
)


def test_course_style_registry_contains_launched_styles() -> None:
    assert set(COURSE_STYLE_TEMPLATES) == {"standard", "dialogue", "story"}
    assert get_course_style_template("standard").label == "标准版"
    assert get_course_style_template("dialogue").label == "对话版"
    assert get_course_style_template("story").label == "故事版"


def test_unknown_or_missing_style_falls_back_to_story() -> None:
    assert normalize_course_content_style(None) == "story"
    assert normalize_course_content_style("unknown") == "story"


def test_prompt_context_expands_trusted_rules() -> None:
    context = course_style_prompt_context("dialogue")
    assert context["id"] == "dialogue"
    assert context["version"] == 1
    assert any("老师" in rule for rule in context["teachingRules"])
    assert any("自测" in rule for rule in context["questionRules"])


def test_story_prompt_context_exposes_full_runtime_contract() -> None:
    context = course_style_prompt_context("story")
    # v6（2026-08-29）：01课前准备不再生成任何问题列表
    assert context["version"] == 6
    assert context["planningRules"]
    assert context["preparationRules"]
    assert context["explanationRules"]
    assert context["exampleRules"]
    assert context["practiceRules"]
    assert context["continuityRules"]
    assert context["reviewRules"]
    assert any("只生成背景引导" in rule for rule in context["preparationRules"])
    assert any("不生成任何问题列表" in rule for rule in context["preparationRules"])
    assert any("3至8个" in rule for rule in context["explanationRules"])
    assert any("2至4道独立变式" in rule for rule in context["exampleRules"])
