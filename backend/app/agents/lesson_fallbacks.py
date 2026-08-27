from __future__ import annotations

from typing import Any

def _backup_study_guide(task: dict[str, Any], lesson_input: dict[str, Any]) -> dict[str, Any]:
    """模型讲义连续两次未通过校验时的确定性降级讲义。

    保证学习单元始终有可用内容（考点 + 例题 + 目标/清单），并通过 require_self_test=False
    的讲义校验；自测覆盖由 _backup_practice_questions 配合 normalize_practice_questions 联动补齐。
    """
    task_id = str(task.get("id", ""))
    course = lesson_input.get("course") if isinstance(lesson_input.get("course"), dict) else {}
    course_name = str(course.get("name") or "本课程")
    task_title = str(task.get("title") or "本学习单元")
    task_desc = str(task.get("description") or "")
    knowledge_point = lesson_input.get("knowledgePoint") if isinstance(lesson_input.get("knowledgePoint"), dict) else {}
    point_name = str(knowledge_point.get("name") or task_title)
    point_summary = str(
        knowledge_point.get("summary")
        or task_desc
        or f"围绕{course_name}的「{point_name}」梳理核心定义、公式适用条件与典型题型。"
    )
    source = str(task.get("source") or knowledge_point.get("source") or "当前课程资料与复习计划")
    exam_point_id = f"{task_id}-ep-1"
    explanation = (
        f"本节聚焦「{point_name}」。{point_summary} "
        f"复习时先确认该知识点在{course_name}中的定义与适用条件，再结合资料里的典型题型练习。"
        f"（本讲义为降级模板，建议在资料更新后重新生成复习主线以获取更贴合的讲解。）"
    )
    guide = {
        "planningReason": (
            f"模型生成的讲义暂未通过校验，已用基于「{point_name}」的降级模板补齐，确保学习单元有可用内容。"
        ),
        "examPoints": [
            {
                "id": exam_point_id,
                "title": point_name,
                "importance": "high",
                "teachingMode": "concept",
                "explanation": explanation,
                "sourceRefs": [source],
                "formulas": [],
                "procedure": [],
                "questionTypes": [],
                "pitfalls": [],
            }
        ],
        "workedExamples": [
            {
                "id": f"{task_id}-ex-1",
                "title": f"「{point_name}」典型例题",
                "problem": f"围绕{course_name}的「{point_name}」，结合资料中的定义与适用条件完成一道基础例题。",
                "analysis": (
                    f"先回顾「{point_name}」的核心定义与适用条件：{point_summary} "
                    f"再按资料中的标准步骤代入求解，并核验结论是否符合题意。"
                ),
                "steps": [
                    f"明确「{point_name}」的适用条件与已知量",
                    "代入资料要求的关系或公式，注意单位与方向",
                    "核验中间结果与最终结论是否与题干一致",
                ],
                "answer": f"按上述步骤得到符合「{point_name}」定义的结论；具体数值以资料原题为准。",
                "conclusion": f"该例题演示了「{point_name}」的基本求解路径。",
                "checks": ["适用条件是否满足", "单位与方向是否正确", "结论是否回应题干"],
                "source": source,
                "examPointIds": [exam_point_id],
            }
        ],
        "selfTestQuestionIds": [],
        "objectives": [
            f"理解「{point_name}」的定义与适用条件",
            f"能独立完成「{point_name}」的基础题型",
        ],
        "sourceHighlights": [f"{point_name}：{point_summary}"],
        "concepts": [{"title": point_name, "body": point_summary, "source": source}],
        "checklist": [
            f"已确认「{point_name}」的适用条件",
            "已对照资料核对该单元的典型题型",
        ],
    }
    onboarding = lesson_input.get("onboarding") if isinstance(lesson_input.get("onboarding"), dict) else {}
    if str(onboarding.get("contentStyle") or "story") == "story":
        main_event = f"主要人物在一个连续任务中需要正确判断「{point_name}」"
        incoming = f"面对事件中的变化，怎样准确识别并运用「{point_name}」？"
        outgoing = str((lesson_input.get("storyContinuity") or {}).get("nextLessonTitle") or "条件继续变化时，判断方法是否仍然成立？")
        guide["storyContext"] = {
            "characters": ["学习者"], "setting": f"与{course_name}知识结构对应的连续任务场景",
            "mainEvent": main_event, "incomingQuestion": incoming, "outgoingQuestion": outgoing,
            "conceptMappings": [{"storyElement": "人物识别条件并采取行动", "concept": point_name, "explanation": point_summary}],
        }
        main_example = guide["workedExamples"][0]
        main_example["independentVariant"] = False
        variants = [
            {**main_example, "id": f"{task_id}-variant-1", "title": f"独立变式一：改变「{point_name}」的一个条件", "problem": f"脱离主故事，改变一个关键条件后重新判断「{point_name}」。", "independentVariant": True},
            {**main_example, "id": f"{task_id}-variant-2", "title": f"独立变式二：纠正「{point_name}」的错误路径", "problem": f"给出一个常见错误判断，指出错因并用正确条件重新判断「{point_name}」。", "independentVariant": True},
        ]
        guide["workedExamples"] = [main_example, *variants]
        guide["sections"] = [
            {"kind": "preparation", "label": "课前准备", "title": f"事件开始：先看清「{point_name}」", "narrative": f"学习者进入一个与「{point_name}」直接相关的轻量场景。接下来沿着这个变化解释判断为何成立。", "questions": [incoming], "terms": [{"term": point_name, "meaning": point_summary, "storyMapping": "人物需要识别的关键条件", "role": "为02的正式因果讲解建立术语底座"}]},
            {"kind": "explanation", "label": "讲解", "title": f"什么条件决定「{point_name}」的判断", "narrative": f"接住刚才的同一变化。{explanation}", "explanationBeats": [{"heading": heading, "body": body, "conclusion": point_summary, "pitfall": "核对定义、条件和边界"} for heading, body in [("对象发生了什么变化？", point_summary), ("为什么会出现这种变化？", explanation), ("哪些条件决定判断？", point_summary), ("怎样把条件连成判断方法？", explanation)]], "methodSummary": ["识别对象", "核对条件", "沿因果关系判断", "检查边界"], "transitionToExamples": "判断方法已经形成，下面把同一事件推进成一道综合例题。"},
            {"kind": "examples", "label": "例题", "title": "把同一事件变成一道综合题", "narrative": f"接住讲解中的事件进展，用刚形成的方法检验「{point_name}」。", "storyEventRef": main_event, "workedExamples": guide["workedExamples"], "methodSummary": ["先识别条件，再选择关系，最后复核边界"], "transitionToSelfCheck": "主例题和独立变式完成后，04将撤去故事与提示，转为独立作答。"},
            {"kind": "self-check", "label": "自测", "title": "离开故事提示独立判断", "narrative": "现在保留技术条件，撤去人物提示，独立完成自测。", "checklist": guide["checklist"]},
        ]
    return guide


def _backup_practice_questions(task: dict[str, Any], guide: dict[str, Any]) -> list[dict[str, Any]]:
    """模型自测连续两次未通过校验时的确定性降级题：每个考点一道单选，examPointIds 联动考点。"""
    task_id = str(task.get("id", ""))
    raw_points = guide.get("examPoints") if isinstance(guide.get("examPoints"), list) else []
    exam_points = [point for point in raw_points if isinstance(point, dict)]
    if not exam_points:
        exam_points = [
            {
                "id": f"{task_id}-ep-1",
                "title": str(task.get("title") or "本学习单元"),
                "explanation": str(task.get("description") or "围绕本单元核心定义、公式条件与典型解法作答。"),
            }
        ]
    questions: list[dict[str, Any]] = []
    for index, point in enumerate(exam_points, start=1):
        point_id = str(point.get("id") or f"{task_id}-ep-{index}")
        title = str(point.get("title") or "本考点")
        explanation = str(point.get("explanation") or "围绕该考点的定义、适用条件与典型解法作答。")
        source_refs = point.get("sourceRefs")
        source = (
            str(source_refs[0])
            if isinstance(source_refs, list) and source_refs and str(source_refs[0]).strip()
            else str(point.get("source") or task.get("source") or "当前课程资料与复习计划")
        )
        questions.append(
            {
                "id": f"{task_id}-q-{index}",
                "type": "single",
                "questionType": "主线学习",
                "score": 5,
                "prompt": f"关于「{title}」，下列哪一项最符合资料中的核心要求？",
                "options": [
                    explanation,
                    "只需记忆关键词，不必理解适用条件与公式含义。",
                    "解题时可以跳过条件判断、单位与方向检查。",
                    "应以个人经验直接得出结论，无需对照资料。",
                ],
                "answerIndex": 0,
                "explanation": f"本题考查「{title}」的核心理解。{explanation}",
                "knowledgePointId": str(task.get("knowledgePointId", "")),
                "source": source,
                "taskId": task_id,
                "examPointIds": [point_id],
            }
        )
    return questions
