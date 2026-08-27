from __future__ import annotations

import json
import random
import re
from typing import Any

from .formula_rules import with_structured_formula_rules
from .workflow_types import JsonModelCall
from ..knowledge_service import retrieve_material_context

def _shuffle_single_choice_options(question: dict[str, Any]) -> dict[str, Any]:
    if str(question.get("type", "single")) != "single":
        return question
    options = question.get("options")
    answer_index = question.get("answerIndex")
    if not isinstance(options, list) or len(options) < 2:
        return question
    if not isinstance(answer_index, int) or not 0 <= answer_index < len(options):
        return question
    paired = list(enumerate(options))  # [(原下标, 选项文本), ...]
    random.shuffle(paired)
    question["options"] = [text for _, text in paired]
    question["answerIndex"] = next(
        new_index for new_index, (original_index, _) in enumerate(paired) if original_index == answer_index
    )
    return question


def _shuffle_single_choice_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对一组题目中的所有单选题就地洗牌（模拟题/诊断题等列表出口使用）。"""
    for question in questions:
        if isinstance(question, dict):
            _shuffle_single_choice_options(question)
    return questions




def _strong_feedback_issues(guide: dict[str, Any], directives: list[str]) -> list[str]:
    """Turn supported MUST feedback into deterministic reviewer failures, not prompt suggestions."""
    if not directives:
        return []
    normalized = "\n".join(directives)
    preparation_requested = any(token in normalized for token in ("课前准备", "preparation", "01"))
    if not preparation_requested:
        return []
    sections = guide.get("sections") if isinstance(guide.get("sections"), list) else []
    by_kind = {str(item.get("kind")): item for item in sections if isinstance(item, dict)}
    preparation = by_kind.get("preparation")
    explanation = by_kind.get("explanation")
    issues: list[str] = []
    if not isinstance(preparation, dict):
        return ["用户强反馈未执行：缺少01-课前准备"]
    terms = preparation.get("terms")
    if not isinstance(terms, list) or not terms or any(not isinstance(item, dict) or not str(item.get("term") or "").strip() or not str(item.get("meaning") or "").strip() for item in terms):
        issues.append("用户强反馈未执行：01必须包含本节关键词及解释")
    questions = preparation.get("questions")
    if isinstance(questions, list) and len(questions) > 1:
        issues.append("用户强反馈未执行：01只允许最多1个用于衔接02的问题，不能沿用3至5题旧模板")
    narrative = str(preparation.get("narrative") or "").strip()
    if not narrative:
        issues.append("用户强反馈未执行：01缺少简短背景引导")
    if len(narrative) > 900:
        issues.append("用户强反馈未执行：01背景引导过长，混入了完整讲解")
    explanation_text = str(explanation.get("narrative") or "").strip() if isinstance(explanation, dict) else ""
    if not explanation_text:
        issues.append("用户强反馈未执行：缺少01结尾与02讲解开头的衔接")
    return issues


def _question_issues(questions: Any, *, collection: str) -> list[str]:
    if not isinstance(questions, list) or not questions:
        return [f"{collection} 为空或格式无效"]
    issues: list[str] = []
    seen_ids: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            issues.append(f"{collection} 包含非对象项")
            continue
        question_id = str(question.get("id", "")).strip()
        if not question_id or question_id in seen_ids:
            issues.append(f"{collection} 题目 id 缺失或重复")
        seen_ids.add(question_id)
        question_type = str(question.get("type", "single")).strip()
        question_label = str(question.get("questionType", "")).strip()
        if collection == "模拟题" and any(keyword in question_label for keyword in ("计算", "综合", "填空", "简答", "论述", "证明")) and question_type != "calculation":
            issues.append(f"题目 {question_id} 标为{question_label}，但 type 不是 calculation")
        is_written_mock = collection == "模拟题" and question_type == "calculation"
        options = question.get("options")
        answer_index = question.get("answerIndex")
        if is_written_mock:
            if not str(question.get("referenceAnswer", "")).strip():
                issues.append(f"题目 {question_id} 缺少计算题参考答案 referenceAnswer")
            if not isinstance(question.get("gradingRubric"), list) or not question.get("gradingRubric"):
                issues.append(f"题目 {question_id} 缺少计算题评分要点 gradingRubric")
        elif not isinstance(options, list) or len(options) < 2:
            issues.append(f"题目 {question_id} 的选项无效")
        elif not isinstance(answer_index, int) or not 0 <= answer_index < len(options):
            issues.append(f"题目 {question_id} 的答案下标无效")
        if collection == "模拟题" and not str(question.get("questionType", "")).strip():
            issues.append(f"题目 {question_id} 缺少真实卷面题型 questionType")
        if not str(question.get("prompt", "")).strip() or not str(question.get("explanation", "")).strip():
            issues.append(f"题目 {question_id} 缺少题干或详细解析")
    return list(dict.fromkeys(issues))


def _mock_question_bucket(question: dict[str, Any]) -> str:
    label = f"{question.get('type', '')} {question.get('questionType', '')}".lower()
    if "填空" in label:
        return "fill"
    if str(question.get("type", "")) == "calculation" or any(
        keyword in label
        for keyword in ("计算", "综合", "填空", "简答", "论述", "证明", "calculation")
    ):
        return "calculation"
    if any(keyword in label for keyword in ("选择", "单选", "单项", "判断", "single")):
        return "choice"
    return "other"


def _extract_mock_score_targets(*values: Any) -> dict[str, int]:
    text = " ".join(str(value) for value in values if value)
    targets: dict[str, int] = {}
    patterns = {
        "choice": (r"(?:选择题?|单选题?|单项选择题?).{0,6}?(\d{1,3})\s*分", r"(\d{1,3})\s*分.{0,6}?(?:选择题?|单选题?|单项选择题?)"),
        "fill": (r"(?:填空题?).{0,6}?(\d{1,3})\s*分", r"(\d{1,3})\s*分.{0,6}?(?:填空题?)"),
        "calculation": (r"(?:计算题?|综合计算题?).{0,6}?(\d{1,3})\s*分", r"(\d{1,3})\s*分.{0,6}?(?:计算题?|综合计算题?)"),
    }
    for bucket, bucket_patterns in patterns.items():
        for pattern in bucket_patterns:
            match = re.search(pattern, text)
            if match:
                targets[bucket] = int(match.group(1))
                break
    return targets


def _mock_blueprint_issues(questions: list[dict[str, Any]], *, onboarding: Any, assessment_profile: Any) -> list[str]:
    onboarding_text = json.dumps(onboarding, ensure_ascii=False) if isinstance(onboarding, dict) else str(onboarding or "")
    assessment_text = json.dumps(assessment_profile, ensure_ascii=False) if isinstance(assessment_profile, dict) else str(assessment_profile or "")
    targets = _extract_mock_score_targets(onboarding_text, assessment_text)
    score_by_bucket = {"choice": 0, "fill": 0, "calculation": 0, "other": 0}
    for question in questions:
        if not isinstance(question, dict):
            continue
        score_by_bucket[_mock_question_bucket(question)] += int(question.get("score", 0))

    issues: list[str] = []
    for bucket, target_score in targets.items():
        if score_by_bucket[bucket] != target_score:
            label = {"choice": "选择题", "fill": "填空题", "calculation": "计算题"}.get(bucket, "其他题")
            issues.append(f"{label}分值应为 {target_score} 分，实际为 {score_by_bucket[bucket]} 分")

    combined_text = f"{onboarding_text} {assessment_text}"
    mentions_calculation = any(keyword in combined_text for keyword in ("计算题", "计算占大头", "计算题占大头", "计算题占大部分"))
    if mentions_calculation and score_by_bucket["calculation"] == 0:
        issues.append("用户说明或资料显示有计算题，但模拟卷没有生成计算题")
    if any(keyword in combined_text for keyword in ("计算题占大头", "计算题占大部分", "计算题占大头")) and score_by_bucket["calculation"] <= score_by_bucket["choice"]:
        issues.append("用户说明计算题占大头，但计算题分值没有高于选择题")
    return issues


def _mock_blueprint_from_context(*, onboarding: Any, assessment_profile: Any, knowledge_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = ("单项选择题", "选择题", "单选题", "填空题", "计算题", "综合题", "简答题", "论述题", "证明题", "判断题")
    entries: list[dict[str, Any]] = []

    def add_entry(label: str, count: int | None = None, score: int | None = None) -> None:
        label = str(label or "").strip()
        if not label:
            return
        existing = next((item for item in entries if item["label"] == label), None)
        if existing:
            if count:
                existing["count"] = count
            if score:
                existing["score"] = score
            return
        entries.append({"label": label, "count": count or 0, "score": score or 0})

    if isinstance(assessment_profile, dict):
        question_types = assessment_profile.get("questionTypes")
        if isinstance(question_types, list):
            for item in question_types:
                if isinstance(item, dict):
                    label = str(item.get("label") or item.get("name") or item.get("type") or item.get("questionType") or "").strip()
                    count = int(item.get("count") or item.get("questions") or 0)
                    score = int(item.get("score") or item.get("points") or 0)
                    add_entry(label, count or None, score or None)
                else:
                    text = str(item)
                    matched_label = next((label for label in labels if label in text), "")
                    count_match = re.search(r"(\d{1,2})\s*(?:道|题)", text)
                    score_match = re.search(r"(\d{1,3})\s*分", text)
                    add_entry(
                        matched_label or text.strip(),
                        int(count_match.group(1)) if count_match else None,
                        int(score_match.group(1)) if score_match else None,
                    )

    onboarding_text = json.dumps(onboarding, ensure_ascii=False) if isinstance(onboarding, dict) else str(onboarding or "")
    assessment_text = json.dumps(assessment_profile, ensure_ascii=False) if isinstance(assessment_profile, dict) else str(assessment_profile or "")
    combined_text = f"{onboarding_text} {assessment_text}"
    label_pattern = "|".join(re.escape(label) for label in labels)
    for match in re.finditer(rf"({label_pattern}).{{0,8}}?(\d{{1,2}})\s*(?:道|题).{{0,8}}?(\d{{1,3}})\s*分", combined_text):
        add_entry(match.group(1), int(match.group(2)), int(match.group(3)))

    targets = _extract_mock_score_targets(onboarding_text, assessment_text)
    if targets.get("choice"):
        add_entry("单项选择题", score=targets["choice"])
    if targets.get("fill"):
        add_entry("填空题", score=targets["fill"])
    if targets.get("calculation"):
        add_entry("计算题", score=targets["calculation"])

    point_count = max(1, len(knowledge_points))
    mentions_written = any(keyword in combined_text for keyword in ("计算题", "综合题", "填空题", "简答题", "论述题", "证明题"))
    if not entries:
        if mentions_written:
            entries = [
                {"label": "单项选择题", "count": min(12, max(4, point_count * 2)), "score": 40},
                {"label": "计算题", "count": min(6, max(2, point_count)), "score": 60},
            ]
        else:
            entries = [{"label": "单项选择题", "count": min(16, max(6, point_count * 2)), "score": 100}]

    for entry in entries:
        score = int(entry.get("score") or 0)
        count = int(entry.get("count") or 0)
        if count <= 0:
            bucket = "choice" if _mock_question_bucket({"questionType": entry["label"]}) == "choice" else "calculation"
            divisor = 3 if bucket == "choice" else 15
            count = max(1, round((score or (40 if bucket == "choice" else 60)) / divisor))
        if score <= 0:
            score = count * (3 if _mock_question_bucket({"questionType": entry["label"]}) == "choice" else 10)
        entry["count"] = max(1, count)
        entry["score"] = max(1, score)
    return entries


def _split_scores(total: int, count: int) -> list[int]:
    count = max(1, count)
    total = max(count, total)
    base = total // count
    remainder = total % count
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _backup_mock_questions(workspace: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    existing_questions = workspace.get("mockQuestions")
    if isinstance(existing_questions, list):
        existing_issues = _question_issues(existing_questions, collection="模拟题")
        existing_issues.extend(
            _mock_blueprint_issues(
                existing_questions,
                onboarding=workspace.get("onboarding", {}),
                assessment_profile=candidate.get("assessmentProfile", workspace.get("assessmentProfile", {})),
            )
        )
        if not existing_issues:
            return existing_questions

    course = workspace.get("course", {}) if isinstance(workspace.get("course"), dict) else {}
    course_name = str(course.get("name") or "本课程")
    points = [point for point in candidate.get("knowledgePoints", []) if isinstance(point, dict)]
    if not points:
        points = [{"id": "diagnostic", "name": course_name, "summary": "根据当前资料、考试说明和复习计划完成综合检查。", "source": "当前课程资料"}]
    points = sorted(points, key=lambda item: int(item.get("weight", 1) or 1), reverse=True)
    entries = _mock_blueprint_from_context(
        onboarding=workspace.get("onboarding", {}),
        assessment_profile=candidate.get("assessmentProfile", workspace.get("assessmentProfile", {})),
        knowledge_points=points,
    )

    questions: list[dict[str, Any]] = []
    question_index = 1
    for entry in entries:
        label = str(entry.get("label") or "模拟题")
        scores = _split_scores(int(entry.get("score") or 1), int(entry.get("count") or 1))
        for local_index, score in enumerate(scores, start=1):
            point = points[(question_index - 1) % len(points)]
            point_id = str(point.get("id") or "diagnostic")
            point_name = str(point.get("name") or course_name)
            point_summary = str(point.get("summary") or "围绕资料中的核心定义、公式、条件和典型题型作答。")
            source = str(point.get("source") or "当前课程资料与复习计划")
            bucket = _mock_question_bucket({"questionType": label})
            if bucket == "choice":
                questions.append(
                    {
                        "id": f"mock-auto-choice-{question_index}",
                        "type": "single",
                        "questionType": label,
                        "score": score,
                        "prompt": f"关于{course_name}的「{point_name}」，下列哪一项最符合当前资料中的核心要求？",
                        "options": [
                            f"{point_summary}",
                            "只需记住题目关键词，不需要结合适用条件判断。",
                            "只要最终答案接近，就可以省略公式、单位和方向检查。",
                            "遇到相关题目时应优先脱离资料自行猜测结论。",
                        ],
                        "answerIndex": 0,
                        "explanation": f"本题检查「{point_name}」的核心理解。应回到资料中的定义、公式条件和典型解法：{point_summary}",
                        "knowledgePointId": point_id,
                        "source": source,
                    }
                )
            else:
                questions.append(
                    {
                        "id": f"mock-auto-written-{question_index}",
                        "type": "calculation",
                        "questionType": label,
                        "score": score,
                        "prompt": f"围绕{course_name}的「{point_name}」完成一道{label}。请写出所用定义或公式、关键步骤、必要条件和最终结论。",
                        "referenceAnswer": f"答案应覆盖「{point_name}」的核心内容：{point_summary}。作答需写明适用条件，给出关键推导或计算步骤，并检查最终结论是否符合题意。",
                        "gradingRubric": [
                            "正确识别考点和适用条件",
                            "写出资料要求的核心公式、定义或方法",
                            "关键步骤完整，必要时包含代入、推导、单位或方向检查",
                            "最终结论明确且与题干要求一致",
                        ],
                        "explanation": f"这道题用于保证模拟卷包含非选择题训练。批改时会按参考答案和评分要点检查「{point_name}」的过程完整性。",
                        "knowledgePointId": point_id,
                        "source": source,
                    }
                )
            question_index += 1
    return questions


def mock_questions_need_repair(workspace: dict[str, Any]) -> bool:
    questions = workspace.get("mockQuestions")
    if not isinstance(questions, list) or not questions:
        return True
    issues = _question_issues(questions, collection="模拟题")
    issues.extend(
        _mock_blueprint_issues(
            questions,
            onboarding=workspace.get("onboarding", {}),
            assessment_profile=workspace.get("assessmentProfile", {}),
        )
    )
    return bool(issues)


def repair_mock_questions(
    course_id: str,
    workspace: dict[str, Any],
    model_json: JsonModelCall,
    *,
    course_prompt: str = "",
    retrieve_context=retrieve_material_context,
) -> dict[str, Any]:
    """Generate a valid mock exam independently from the full content workflow.

    The normal workflow creates mockQuestions only after every lesson build has run. A
    timeout, process restart, or failed final workspace merge can therefore leave an
    otherwise planned course with an empty mock exam. This repair path makes two
    focused model attempts and always falls back to the deterministic blueprint.
    """
    points = [point for point in workspace.get("knowledgePoints", []) if isinstance(point, dict)]
    if not points:
        raise ValueError("课程尚无知识点，无法生成模拟卷")

    prompt = with_structured_formula_rules("""
你是 Exam Question Repair Agent。请为已经完成复习主线规划、但模拟卷缺失或损坏的课程独立生成一套完整模拟题。
优先依据 evidence 中的样卷、真题和考试说明；否则依据 onboarding、assessmentProfile 和知识点动态决定题型、题量及分值。
选择题使用 type=\"single\" 并提供 options、answerIndex、explanation；计算题、填空题、简答题和综合题使用 type=\"calculation\" 并提供 referenceAnswer、gradingRubric、explanation。
只返回 JSON：{\"mockQuestions\":[{\"id\":\"唯一id\",\"type\":\"single|calculation\",\"questionType\":\"题型\",\"score\":整数,\"prompt\":\"完整题干\",\"options\":[\"选择题选项\"],\"answerIndex\":0,\"referenceAnswer\":\"非选择题答案\",\"gradingRubric\":[\"评分点\"],\"explanation\":\"解析\",\"knowledgePointId\":\"已有知识点id\",\"source\":\"资料出处或AI仿题\"}]}
不得伪称真题；knowledgePointId 必须引用输入中的已有知识点。
""")
    query = " ".join(str(point.get("name", "")) for point in points)
    try:
        retrieval = retrieve_context(
            course_id,
            f"{query} 模拟卷 样卷 试卷 真题 考试题型 分值比例 综合题 计算题",
            limit=12,
        )
        evidence = str(retrieval.get("context", ""))
    except Exception:
        evidence = ""

    issues: list[str] = ["模拟卷尚未生成"]
    last_error = ""
    questions: list[dict[str, Any]] = []
    for attempt in range(2):
        payload = {
            "course": workspace.get("course", {}),
            "onboarding": workspace.get("onboarding", {}),
            "assessmentProfile": workspace.get("assessmentProfile", {}),
            "knowledgePoints": points,
            "tasks": [
                {key: value for key, value in task.items() if key != "studyGuide"}
                for task in workspace.get("tasks", [])
                if isinstance(task, dict)
            ],
            "evidence": evidence,
        }
        if attempt:
            payload["questionIssues"] = issues
        try:
            result = model_json(
                prompt if not attempt else prompt + "\n请修复 questionIssues 中的全部问题。",
                json.dumps(payload, ensure_ascii=False),
                course_prompt,
            )
            questions = result.get("mockQuestions") if isinstance(result.get("mockQuestions"), list) else []
            issues = _question_issues(questions, collection="模拟题")
            issues.extend(
                _mock_blueprint_issues(
                    questions,
                    onboarding=workspace.get("onboarding", {}),
                    assessment_profile=workspace.get("assessmentProfile", {}),
                )
            )
            issues = list(dict.fromkeys(issues))
            if not issues:
                _shuffle_single_choice_questions(questions)
                return {"mockQuestions": questions, "source": "model", "warning": ""}
        except Exception as error:
            last_error = str(error)
            issues = [last_error or "模型生成失败"]

    questions = _backup_mock_questions(workspace, workspace)
    fallback_issues = _question_issues(questions, collection="模拟题")
    fallback_issues.extend(
        _mock_blueprint_issues(
            questions,
            onboarding=workspace.get("onboarding", {}),
            assessment_profile=workspace.get("assessmentProfile", {}),
        )
    )
    if fallback_issues:
        raise ValueError("模拟题修复失败：" + "；".join(fallback_issues[:5]))
    _shuffle_single_choice_questions(questions)
    warning = last_error or ("；".join(issues[:5]) if issues else "模型结果不合规")
    return {"mockQuestions": questions, "source": "fallback", "warning": warning}
