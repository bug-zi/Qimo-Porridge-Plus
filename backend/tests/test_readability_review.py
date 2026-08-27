from copy import deepcopy

from app.agents.readability_review import (
    attach_readability_review,
    build_course_readability_review,
    review_study_guide,
)


def _task() -> dict:
    return {
        "id": "lesson-1",
        "title": "进程状态判断",
        "studyGuide": {
            "examPoints": [{
                "id": "ep-1", "title": "状态条件", "explanation": "先识别资源条件，再判断进程状态。",
                "formulas": [{"expression": "state=f(resource,cpu)", "meaning": "状态由资源与处理器条件共同决定", "conditions": "用于状态判断题"}],
                "procedure": ["检查资源是否齐备", "检查是否获得处理器"], "pitfalls": ["就绪不等于运行"],
            }],
            "workedExamples": [{"title": "窗口排队", "problem": "判断当前状态。", "analysis": "识别条件。", "steps": ["检查资源", "给出状态"], "answer": "就绪态"}],
            "sections": [],
        },
    }


def test_clear_standard_lesson_passes_and_does_not_rewrite_content() -> None:
    task = _task()
    before = deepcopy(task["studyGuide"])
    report = attach_readability_review(task, "standard")
    assert report["status"] == "passed"
    assert report["score"] == 100
    stored = task["studyGuide"].pop("readabilityReview")
    assert stored == report
    assert task["studyGuide"] == before


def test_dense_text_duplicate_headings_and_formula_context_are_reported() -> None:
    task = _task()
    task["studyGuide"]["examPoints"] = [
        {"title": "重复标题", "explanation": "很长" * 150, "formulas": [{"expression": "x=1", "meaning": "", "conditions": ""}]},
        {"title": "重复标题", "explanation": "短讲解", "formulas": []},
    ]
    report = review_study_guide(task)
    codes = {issue["code"] for issue in report["issues"]}
    assert report["status"] == "attention"
    assert {"dense-paragraph", "formula-context", "duplicate-heading"} <= codes


def test_course_report_counts_partial_generation() -> None:
    ready = _task()
    pending = {"id": "lesson-2", "title": "待生成"}
    orientation = {"id": "orientation", "kind": "orientation", "studyGuide": {}}
    report = build_course_readability_review([orientation, ready, pending])
    assert report["reviewedLessonCount"] == 1
    assert report["passedLessonCount"] == 1
    assert report["pendingLessonCount"] == 1
    assert report["status"] == "attention"

def test_manual_review_service_persists_course_and_lesson_reports(monkeypatch) -> None:
    from app import study_service

    workspace = {
        "course": {"id": "course-1"},
        "onboarding": {"contentStyle": "standard"},
        "tasks": [_task(), {"id": "lesson-2", "title": "待生成"}],
    }
    saved: dict = {}
    monkeypatch.setattr(study_service, "load_workspace", lambda *args, **kwargs: workspace)
    monkeypatch.setattr(study_service, "save_workspace", lambda value, course_id: saved.update({"workspace": value, "courseId": course_id}))

    result = study_service.review_course_readability("course-1")
    assert result["readabilityReview"]["reviewedLessonCount"] == 1
    assert result["readabilityReview"]["pendingLessonCount"] == 1
    assert result["tasks"][0]["studyGuide"]["readabilityReview"]["status"] == "passed"
    assert saved["courseId"] == "course-1"
