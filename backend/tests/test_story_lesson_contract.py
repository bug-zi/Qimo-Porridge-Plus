from app.agents.workflow import _study_guide_issues
from app.study_service import _build_study_guide_sections


def _story_guide() -> dict:
    example = {
        "id": "task-1-ex-1", "title": "同一事件例题", "source": "资料",
        "problem": "完整题干", "analysis": "判断关键条件", "steps": ["识别条件", "得出结论"],
        "answer": "答案", "checks": ["核对边界"], "examPointIds": ["ep-1"],
    }
    main_example = {**example, "independentVariant": False}
    variant_one = {**example, "id": "task-1-var-1", "title": "独立变式一", "independentVariant": True}
    variant_two = {**example, "id": "task-1-var-2", "title": "独立变式二", "independentVariant": True}
    return {
        "examPoints": [{
            "id": "ep-1", "title": "进程状态", "importance": "high", "teachingMode": "application",
            "explanation": "根据是否占用处理器以及等待的资源判断状态。", "sourceRefs": ["讲义"],
            "formulas": [], "procedure": ["识别条件"], "questionTypes": ["状态判断"], "pitfalls": ["混淆就绪与阻塞"],
        }],
        "workedExamples": [main_example, variant_one, variant_two], "selfTestQuestionIds": [],
        "storyContext": {
            "characters": ["小周"], "setting": "办事大厅", "mainEvent": "小周办理一项连续业务",
            "incomingQuestion": "为什么有时排队有时必须等材料？", "outgoingQuestion": "调度发生时状态怎样变化？",
            "conceptMappings": [{"storyElement": "等待窗口", "concept": "就绪态", "explanation": "条件齐备但未获得处理器"}],
        },
        "sections": [
            {"kind": "preparation", "label": "课前准备", "title": "业务为什么停下", "narrative": "同一事件开始，并自然引向状态为什么变化。", "questions": ["状态为什么变化？"], "terms": [{"term": "进程状态", "meaning": "进程当前阶段", "storyMapping": "业务所处阶段", "role": "为状态判断建立术语底座"}]},
            {"kind": "explanation", "label": "讲解", "title": "等待条件决定状态", "narrative": "接住同一事件解释术语。", "explanationBeats": [{"heading": f"问题{i}", "body": "沿因果解释。", "conclusion": "准确结论"} for i in range(1, 5)], "methodSummary": ["识别条件", "判断状态"], "transitionToExamples": "下面把状态变化放进题目。"},
            {"kind": "examples", "label": "例题", "title": "条件第一次变化", "narrative": "接住讲解进入题目。", "storyEventRef": "小周办理一项连续业务", "workedExamples": [main_example, variant_one, variant_two], "methodSummary": ["识别条件后判断"], "transitionToSelfCheck": "04撤去故事提示，转为独立作答。"},
            {"kind": "self-check", "label": "自测", "title": "撤去故事提示", "narrative": "独立判断。"},
        ],
    }


def test_story_validator_requires_first_class_story_contract() -> None:
    guide = _story_guide()
    issues = _study_guide_issues({"id": "task-1", "_contentStyle": "story", "studyGuide": guide}, {}, require_self_test=False)
    assert issues == []

    del guide["storyContext"]["mainEvent"]
    issues = _study_guide_issues({"id": "task-1", "_contentStyle": "story", "studyGuide": guide}, {}, require_self_test=False)
    assert any("mainEvent" in issue for issue in issues)


def test_story_validator_rejects_wrong_order_and_event_reference() -> None:
    guide = _story_guide()
    guide["sections"][0], guide["sections"][1] = guide["sections"][1], guide["sections"][0]
    guide["sections"][2]["storyEventRef"] = "另一个无关事件"
    issues = _study_guide_issues({"id": "task-1", "_contentStyle": "story", "studyGuide": guide}, {}, require_self_test=False)
    assert any("必须恰好按" in issue for issue in issues)
    assert any("mainEvent 不一致" in issue for issue in issues)


def test_standard_validator_remains_backward_compatible() -> None:
    guide = _story_guide()
    guide.pop("storyContext")
    guide.pop("sections")
    assert _study_guide_issues({"id": "task-1", "studyGuide": guide}, {}, require_self_test=False) == []


def test_story_sections_are_not_overwritten_by_legacy_normalizer() -> None:
    guide = _story_guide()
    assert _build_study_guide_sections(guide) is guide["sections"]

def test_story_validator_rejects_old_shallow_section_shapes() -> None:
    guide = _story_guide()
    preparation = guide["sections"][0]
    preparation["questions"] = ["问题1", "问题2", "问题3"]
    explanation = guide["sections"][1]
    explanation["explanationBeats"] = explanation["explanationBeats"][:2]
    examples = guide["sections"][2]
    examples["workedExamples"] = examples["workedExamples"][:1]
    issues = _study_guide_issues({"id": "task-1", "_contentStyle": "story", "studyGuide": guide}, {}, require_self_test=False)
    assert any("最多1个" in issue for issue in issues)
    assert any("4至7个" in issue for issue in issues)
    assert any("1个主故事综合例题" in issue for issue in issues)

