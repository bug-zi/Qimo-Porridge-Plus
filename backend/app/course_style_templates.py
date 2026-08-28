from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

CourseContentStyle = Literal["standard", "dialogue", "story"]
DEFAULT_COURSE_CONTENT_STYLE: CourseContentStyle = "story"


@dataclass(frozen=True)
class CourseStyleTemplate:
    id: CourseContentStyle
    label: str
    version: int
    teaching_rules: tuple[str, ...]
    question_rules: tuple[str, ...]
    output_rules: tuple[str, ...]
    planning_rules: tuple[str, ...] = ()
    preparation_rules: tuple[str, ...] = ()
    explanation_rules: tuple[str, ...] = ()
    example_rules: tuple[str, ...] = ()
    practice_rules: tuple[str, ...] = ()
    continuity_rules: tuple[str, ...] = ()
    review_rules: tuple[str, ...] = ()


_COMMON_OUTPUT_RULES = (
    "生成课前准备、讲解、例题、自测四份相互衔接的内容；01→02 从问题进入解释，02→03 从方法进入示范，03→04 从带练进入独立判断。",
    "只使用资料支持的知识，不为结构完整硬凑知识点或技术事实。",
    "语言直接、亲切且有信息量；删除无信息安抚、目录播报和机械重复，禁用‘不是……而是……’及其机械变体。",
    "为屏幕阅读排版：每个标题只承担一个信息重点；正文使用短段落，长推理拆成可扫描步骤，结论、适用边界与易错点分层表达。",
)

COURSE_STYLE_TEMPLATES: dict[CourseContentStyle, CourseStyleTemplate] = {
    "standard": CourseStyleTemplate(
        id="standard",
        label="标准版",
        version=1,
        teaching_rules=(
            "采用清晰、直接的标准讲义结构，先建立核心对象关系，再按定义、解释、边界和应用展开。",
            "以事实密度和检索效率为优先，不强制设置人物、连续故事或对话角色。",
            "小结转化为可执行的判断步骤，不使用机械因果链复述全文。",
        ),
        question_rules=(
            "例题先给结论，再解释决定答案的关键条件；变式每次改变一个关键条件。",
            "自测保持独立作答，干扰项来自真实误区，答案集中放在文末。",
        ),
        output_rules=_COMMON_OUTPUT_RULES,
    ),
    "dialogue": CourseStyleTemplate(
        id="dialogue",
        label="对话版",
        version=1,
        teaching_rules=(
            "采用老师与一名或多名学生的教学对话推进课程；每轮对话必须承担提问、尝试判断、澄清误区或推进因果中的至少一项。",
            "老师不连续灌输长段定义，学生也不机械复述刚讲过的话；用真实疑问和典型错误推动下一概念。",
            "对话中的口语表达必须准确落回标准术语，删除寒暄、表演性互动和无信息回应。",
        ),
        question_rules=(
            "例题可由老师逐步追问，学生先尝试判断，随后共同指出决定答案的条件；必须保留完整答案。",
            "自测脱离老师提示，让学生独立作答；参考答案可用简短讲评口吻，但不能继续代替学生完成推理。",
        ),
        output_rules=_COMMON_OUTPUT_RULES + (
            "对话角色名称保持稳定，发言短而有效；连续多轮只换说话人但没有新增信息时，合并或删除。",
        ),
    ),
    "story": CourseStyleTemplate(
        id="story",
        label="故事版",
        version=6,
        teaching_rules=(
            "采用一条连续、生活化的故事主线，让人物行动自然制造问题、展示条件变化、暴露误区并推动应用。",
            "人物必须有名有姓且有具体生活情境（如小林、阿哲），禁止用“学习者”“同学”等泛称呼当人名；人物行动要具体到文件、按钮、报错等细节。",
            "narrative 与讲解正文是给学生阅读的正文本身，写成完整自然段；禁止舞台说明式概括和“先别急着记概念”式导读腔。",
            "类比必须与当前概念结构准确对应，并在同段或紧邻段落落回标准术语；同一课程尽量不切换比喻体系。",
        ),
        question_rules=(
            "主例题延续故事事件并由识别推进到因果；变式改变关键条件，至少一道要求纠正错误路径或解释原因。",
            "自测逐步降低故事辅助，检查学生能否离开叙事带领后独立判断和迁移。",
        ),
        output_rules=_COMMON_OUTPUT_RULES + (
            "每个概念只落一次结论，采用‘定义后阐释’或‘生动描述后总结’其中一种结构。",
        ),
        planning_rules=(
            "先列出资料支持的事实、边界和误区，再选择结构相似的日常场景，设定一名主要人物和一个贯穿事件。",
            "按知识前置关系安排人物遇到的问题；每个动作必须映射技术概念，情节只用于制造问题、展示条件变化、暴露误区或推动应用。",
        ),
        preparation_rules=(
            "01-课前准备的职责是让学生愿意进入课程，并为正式讲解建立场景和术语底座；只生成背景引导、本节关键词解释、以及01结尾到02开头的衔接。",
            "背景引导采用一个与主题直接相关的具体事件，写成2至3个自然段的故事散文，让核心对象在事件中自然出现；关键词按02使用顺序排列，每个词分别给出准确解释、场景对应和本节作用。",
            "不生成学习目标播报、例题、关系链、口诀或重复总结；不生成任何问题列表，02讲解自然接住01结尾的悬念即可。",
        ),
        explanation_rules=(
            "02-讲解的职责是讲清结论为什么成立、知识怎样连起来；开头必须接住01的同一事件和最后一句，不使用文档导航式套话。",
            "正文须包含3至8个问题式或事件式二级标题（建议4至7个），每个标题形成一个 explanationBeats 项并沿因果主线推进；每一项都写清因果解释、准确结论及必要边界。",
            "结尾用自然事件进展引出03-例题。",
        ),
        example_rules=(
            "03-例题的职责是把02中的判断方法放进题目；开头承接02的事件进展，结构固定为1个主故事综合例题加2至4道独立变式。",
            "主例题引用同一mainEvent并综合运用判断方法；独立变式脱离主故事，每题改变一个关键条件，其中至少一道纠正错误路径或解释原因。",
            "结尾总结这组训练实际使用的判断方法，并明确说明04将撤去故事与提示、转为独立作答。",
        ),
        practice_rules=(
            "自测题脱离人物提示，独立覆盖核心概念、关系、条件和边界；干扰项来自真实误区。",
            "答案先直接回答再解释并独立复核，不考查讲解未覆盖的核心知识。",
        ),
        continuity_rules=(
            "课前准备到讲解是问题到解释，讲解到例题是方法到示范，例题到自测是带练到独立判断。",
            "前后课程通过incomingQuestion和outgoingQuestion承接；人物、场景、贯穿事件、术语、事实、限定和概念映射保持一致。",
        ),
        review_rules=(
            "拒绝缺少storyContext、mainEvent、前后承接问题或conceptMappings的输出。",
            "拒绝各考点使用互不相关类比、故事例题未引用同一事件、存在无教学功能情节或‘不是……而是……’机械句式的输出。",
        ),
    ),
}


def normalize_course_content_style(value: object) -> CourseContentStyle:
    normalized = str(value or "").strip().lower()
    if normalized in COURSE_STYLE_TEMPLATES:
        return cast(CourseContentStyle, normalized)
    return DEFAULT_COURSE_CONTENT_STYLE


def get_course_style_template(value: object) -> CourseStyleTemplate:
    return COURSE_STYLE_TEMPLATES[normalize_course_content_style(value)]


def course_style_prompt_context(value: object) -> dict[str, object]:
    template = get_course_style_template(value)
    return {
        "id": template.id,
        "label": template.label,
        "version": template.version,
        "teachingRules": list(template.teaching_rules),
        "questionRules": list(template.question_rules),
        "outputRules": list(template.output_rules),
        "planningRules": list(template.planning_rules),
        "preparationRules": list(template.preparation_rules),
        "explanationRules": list(template.explanation_rules),
        "exampleRules": list(template.example_rules),
        "practiceRules": list(template.practice_rules),
        "continuityRules": list(template.continuity_rules),
        "reviewRules": list(template.review_rules),
    }
